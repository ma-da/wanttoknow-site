#!/usr/bin/env python3
"""Infer draft JSON Schemas and a registry for WantToKnow.info data.

Supported directly:
  .json  -> schema describes the whole document
  .jsonl -> schema describes one record/line
  .csv   -> schema describes one logical row

Binary/native structured artifacts (.sqlite/.db/.npz/.npy/.parquet/.feather)
are inventoried separately because JSON Schema cannot validate their internal
binary structure. They should later get native contracts alongside registry
metadata.

Output defaults to schemas/generated/ so inferred schemas can be reviewed
before promotion to canonical schemas/primary, schemas/derived, or
schemas/reference.
"""
from __future__ import annotations

import argparse, csv, json, math, re, sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DRAFT = "https://json-schema.org/draft/2020-12/schema"
SUPPORTED = {".json", ".jsonl", ".csv"}
NATIVE = {".sqlite", ".sqlite3", ".db", ".npz", ".npy", ".parquet", ".feather"}
DATA_ROOTS = ["src/site/data", "src/site/search/mkultra/assets/data"]
REF_ROOTS = ["backend", "scripts", "src/site/assets/js", "src/site"]
REF_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".html", ".htm", ".md"}
MAX_REF_BYTES = 2 * 1024 * 1024
IGNORE_PARTS = {".git", ".venv", "venv", "__pycache__", "node_modules", "dist", "schemas"}
IGNORE_PREFIXES = {
    "backend/runtime",
    "backend/data/private",
    "src/site/assets/images/article-images",
    "src/site/assets/images/article-thumbs",
    "src/site/search/mkultra/images",
    "src/site/search/mkultra/thumbs",
}
ROLE_OVERRIDES = {
    "src/site/data/archive_stats.json": "derived",
    "src/site/data/reader-praise.json": "primary",
    "src/site/data/elements/headerFooter.json": "primary",
    "src/site/data/substack_raws/posts.csv": "primary",
}
ACCEPTED_AMBIGUITIES = {
    (
        "src-site-data-elements-headerfooter-json",
        "$.menu.priority[]",
        "optional-field-presence",
    ),
}

FIELD_SCHEMA_OVERRIDES = {
    "src-site-data-substack-raws-posts": {
        "post_id": {
            "type": "string",
            "description": (
                "Unique identifier for the Substack post."
            ),
        },
    },
}
IGNORE_FILES = {
    "src/site/data/wtk_articles_master.csv",
}

def posix(p: Path) -> str:
    return p.as_posix().lstrip("./")


def ignored(rel: Path) -> bool:
    s = posix(rel)

    # Explicit individual files that should not participate
    # in schema generation.
    if s in IGNORE_FILES:
        return True

    if set(rel.parts) & IGNORE_PARTS:
        return True

    return any(
        s == x or s.startswith(x + "/")
        for x in IGNORE_PREFIXES
    )


def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower() or "dataset"


def string_format(s: str) -> set[str]:
    out = set()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        out.add("date")
    if "T" in s:
        try:
            datetime.fromisoformat(s.replace("Z", "+00:00"))
            out.add("date-time")
        except ValueError:
            pass
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", s):
        u = urlparse(s)
        if u.scheme and u.netloc:
            out.add("uri")
    return out


def csv_value(raw: str) -> Any:
    v = raw.strip()
    if v == "":
        return None
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if v.lower() in {"null", "none"}:
        return None
    if v[:1] in {"[", "{"}:
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass
    if re.fullmatch(r"-?(?:0|[1-9]\d*)", v):
        try:
            return int(v)
        except ValueError:
            pass
    if re.fullmatch(r"-?(?:\d+\.\d*|\d*\.\d+|\d+(?:[eE][+-]?\d+)|(?:\d+\.\d*|\d*\.\d+)[eE][+-]?\d+)", v):
        try:
            n = float(v)
            if math.isfinite(n):
                return n
        except ValueError:
            pass
    return raw


@dataclass
class Stats:
    seen: int = 0
    types: Counter = field(default_factory=Counter)
    object_count: int = 0
    props: dict[str, "Stats"] = field(default_factory=dict)
    items: "Stats | None" = None
    string_formats: set[str] | None = None

    def add(self, v: Any) -> None:
        self.seen += 1
        if v is None:
            self.types["null"] += 1
        elif isinstance(v, bool):
            self.types["boolean"] += 1
        elif isinstance(v, int):
            self.types["integer"] += 1
        elif isinstance(v, float):
            self.types["number"] += 1
        elif isinstance(v, str):
            self.types["string"] += 1
            f = string_format(v)
            self.string_formats = f if self.string_formats is None else self.string_formats & f
        elif isinstance(v, list):
            self.types["array"] += 1
            if self.items is None:
                self.items = Stats()
            for x in v:
                self.items.add(x)
        elif isinstance(v, dict):
            self.types["object"] += 1
            self.object_count += 1
            for k, x in v.items():
                self.props.setdefault(str(k), Stats()).add(x)
        else:
            self.types["string"] += 1

    def to_schema(self, path: str = "$") -> tuple[dict[str, Any], list[dict[str, Any]]]:
        ambiguities = []
        kinds = list(self.types)
        if "number" in kinds and "integer" in kinds:
            kinds.remove("integer")  # JSON Schema number includes integer
        order = [x for x in ("object", "array", "string", "integer", "number", "boolean", "null") if x in kinds]
        out: dict[str, Any] = {}
        if not order:
            return out, ambiguities
        out["type"] = order[0] if len(order) == 1 else order
        if len([x for x in order if x != "null"]) > 1:
            ambiguities.append({"path": path, "kind": "mixed-types", "types": order, "counts": dict(self.types)})

        if "object" in order:
            out["properties"] = {}
            required = []
            optional = []
            for key in sorted(self.props):
                child, child_amb = self.props[key].to_schema(f"{path}.{key}")
                out["properties"][key] = child
                ambiguities.extend(child_amb)
                if self.props[key].seen == self.object_count:
                    required.append(key)
                else:
                    optional.append({"field": key, "present": self.props[key].seen, "objects": self.object_count})
            if required:
                out["required"] = required
            out["additionalProperties"] = True
            if optional:
                ambiguities.append({"path": path, "kind": "optional-field-presence", "fields": optional})

        if "array" in order:
            if self.items and self.items.seen:
                out["items"], amb = self.items.to_schema(path + "[]")
                ambiguities.extend(amb)
            else:
                out["items"] = {}

        if "string" in order and self.string_formats and len(self.string_formats) == 1:
            out["format"] = next(iter(self.string_formats))
        return out, ambiguities


def discover(repo: Path, roots: list[str]) -> tuple[list[Path], list[Path]]:
    good, native = [], []
    seen = set()
    for root in roots:
        base = repo / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(repo)
            if rel in seen or ignored(rel):
                continue
            seen.add(rel)
            s = p.suffix.lower()
            if s in SUPPORTED:
                good.append(rel)
            elif s in NATIVE:
                native.append(rel)
    return sorted(good), sorted(native)


def group_key(rel: Path) -> str:
    return posix(rel.with_suffix("")) if rel.suffix.lower() in {".csv", ".jsonl"} else posix(rel)


def scan_file(path: Path, suffix: str, stats: Stats, limit: int) -> tuple[int, bool]:
    if suffix == ".json":
        with path.open("r", encoding="utf-8-sig") as f:
            stats.add(json.load(f))
        return 1, True
    count = 0
    complete = True
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8-sig") as f:
            for line_no, line in enumerate(f, 1):
                if not line.strip():
                    continue
                if limit and count >= limit:
                    complete = False
                    break
                try:
                    stats.add(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"invalid JSONL line {line_no}: {e}") from e
                count += 1
    elif suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None:
                raise ValueError("CSV has no header")
            for row in reader:
                if limit and count >= limit:
                    complete = False
                    break
                stats.add({k: csv_value(v or "") for k, v in row.items() if k is not None})
                count += 1
    return count, complete


def suggest_role(paths: list[Path]) -> tuple[str, list[str]]:
    # Explicit project classifications always win.
    for path in paths:
        override = ROLE_OVERRIDES.get(posix(path))

        if override:
            return (
                override,
                ["explicit project classification"],
            )

    text = " ".join(
        posix(p).lower()
        for p in paths
    )

    derived = [
        x
        for x in (
            "index",
            "related",
            "tfidf",
            "matrix",
            "features",
            "chunks",
            "corpus",
            "redirect",
            "search",
            "registry",
        )
        if x in text
    ]

    reference = [
        x
        for x in (
            "canonicalization",
            "headerfooter",
            "header-footer",
            "category-map",
            "config",
            "normalization",
        )
        if x in text
    ]

    primary = [
        x
        for x in (
            "master",
            "timeline",
            "article",
            "page",
            "youtube",
            "substack",
        )
        if x in text
    ]

    reasons = []

    if derived:
        reasons.append(
            "derived-name hints: "
            + ", ".join(derived)
        )

    if reference:
        reasons.append(
            "reference/config hints: "
            + ", ".join(reference)
        )

    if primary:
        reasons.append(
            "primary-name hints: "
            + ", ".join(primary)
        )

    if derived and not reference:
        return "derived", reasons

    if reference and not derived:
        return "reference/config", reasons

    if primary and not derived and not reference:
        return "primary", reasons

    return "unclassified", reasons


def references(repo: Path, data_files: list[Path]) -> dict[str, list[str]]:
    needles = {posix(p): {posix(p), "/" + posix(p), p.name} for p in data_files}
    out = {posix(p): [] for p in data_files}
    candidates = []
    seen = set()
    for root in REF_ROOTS:
        base = repo / root
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in REF_SUFFIXES:
                continue
            rel = p.relative_to(repo)
            if rel in seen or ignored(rel):
                continue
            seen.add(rel)
            try:
                if p.stat().st_size <= MAX_REF_BYTES:
                    candidates.append(rel)
            except OSError:
                pass
    for rel in sorted(candidates):
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for dp, terms in needles.items():
            if any(t in text for t in terms):
                out[dp].append(posix(rel))
    return out


def native_contract(suffix: str) -> str:
    if suffix in {".sqlite", ".sqlite3", ".db"}:
        return "SQLite DDL/schema manifest + registry metadata"
    if suffix in {".npz", ".npy"}:
        return "array-name/dtype/shape manifest + registry metadata"
    if suffix in {".parquet", ".feather"}:
        return "Arrow/Parquet schema + registry metadata"
    return "native format contract + registry metadata"


def dump(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def readme(reg: dict[str, Any]) -> str:
    lines = [
        "# Generated WantToKnow.info Data Schema Inventory", "",
        "> **Draft output.** Review before promoting schemas to canonical `schemas/primary/`,",
        "> `schemas/derived/`, or `schemas/reference/`.", "",
        "## Conventions", "",
        "- JSON Schema dialect: Draft 2020-12.",
        "- `.json` schemas describe the whole document.",
        "- `.jsonl` schemas describe one record per line.",
        "- `.csv` schemas describe one logical row after conservative type decoding.",
        "- `role_suggestion` is heuristic only.",
        "- `referenced_by` is a literal source reference scan, not proof of runtime use.",
        "- Generated schemas keep `additionalProperties: true` until reviewed.", "",
        "## Structured datasets", "",
        "| Dataset | Suggested role | Files | Schema | Records scanned |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for d in reg["datasets"]:
        files = "<br>".join(f"`{p}`" for p in d["files"])
        records = sum(x.get("records_scanned", 0) for x in d["file_scan"])
        lines.append(f"| `{d['id']}` | {d['role_suggestion']} | {files} | `{d['schema']}` | {records:,} |")
    lines += ["", "## Review workflow", "",
              "1. Confirm primary / derived / reference-config role.",
              "2. Review `ambiguities.json`, especially mixed types and optional fields.",
              "3. Add field descriptions and semantic constraints.",
              "4. Tighten enums, patterns, URI/date rules, ranges, and `additionalProperties`.",
              "5. Promote reviewed schemas into canonical directories.",
              "6. Update the canonical registry to point to promoted schemas.", ""]
    if reg["unsupported_artifacts"]:
        lines += ["## Native/binary structured artifacts", "",
                  "JSON Schema cannot directly validate these formats; give them native contracts as well.", "",
                  "| Path | Format | Recommended contract |", "| --- | --- | --- |"]
        for x in reg["unsupported_artifacts"]:
            lines.append(f"| `{x['path']}` | `{x['suffix']}` | {x['recommended_contract']} |")
        lines.append("")
    lines += ["## Important", "",
              "Generated schemas document observed structure, not automatically authoritative business rules.",
              "After review, canonical schemas should be shared by admin validation, build scripts, tests, and deployment preflight.", ""]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="WantToKnow.info repository root.",
    )
    ap.add_argument("--output", default="schemas/generated")
    ap.add_argument("--data-root", action="append", dest="roots")
    ap.add_argument("--max-records", type=int, default=0, help="0 = full scan")
    ap.add_argument("--no-references", action="store_true")
    args = ap.parse_args()

    repo = args.repo.resolve()
    roots = args.roots or DATA_ROOTS
    output = repo / args.output
    good, native = discover(repo, roots)
    if not good and not native:
        print("No structured data files found.", file=sys.stderr)
        return 1

    groups: dict[str, list[Path]] = {}
    for rel in good:
        groups.setdefault(group_key(rel), []).append(rel)
    refs = {} if args.no_references else references(repo, good)

    datasets, all_amb = [], []
    for key, files in sorted(groups.items()):
        dataset_id = slug(key)
        stats = Stats()
        scans, local_amb = [], []
        for rel in sorted(files):
            p = repo / rel
            row = {"path": posix(rel), "format": p.suffix.lower().lstrip("."), "bytes": p.stat().st_size}
            try:
                n, complete = scan_file(p, p.suffix.lower(), stats, args.max_records)
                row.update(records_scanned=n, scan_complete=complete)
            except Exception as e:
                row["error"] = str(e)
                row.update(records_scanned=0, scan_complete=False)
                local_amb.append({"dataset": dataset_id, "path": posix(rel), "kind": "scan-error", "message": str(e)})
            scans.append(row)

        body, amb = stats.to_schema()

        # ------------------------------------------------------------
        # Apply explicit field-level schema decisions.
        # ------------------------------------------------------------

        field_overrides = FIELD_SCHEMA_OVERRIDES.get(
            dataset_id,
            {},
        )

        if field_overrides:
            properties = body.setdefault(
                "properties",
                {},
            )

            for field_name, field_schema in field_overrides.items():
                properties[field_name] = field_schema


        # ------------------------------------------------------------
        # Remove ambiguities that have been explicitly reviewed and
        # accepted as intentional project structure.
        # ------------------------------------------------------------

        resolved_amb = []

        for item in amb:
            key = (
                dataset_id,
                item.get("path"),
                item.get("kind"),
            )

            # post_id has an explicit canonical schema override.
            if (
                dataset_id
                == "src-site-data-substack-raws-posts"
                and item.get("path") == "$.post_id"
                and item.get("kind") == "mixed-types"
            ):
                continue

            if key in ACCEPTED_AMBIGUITIES:
                continue

            resolved_amb.append(item)

        amb = resolved_amb

        local_amb.extend(
            {
                "dataset": dataset_id,
                **x,
            }
            for x in amb
        )

        role, reasons = suggest_role(files)
        schema_name = dataset_id + ".schema.json"
        schema_rel = f"generated/{schema_name}"
        schema_doc = {
            "$schema": DRAFT,
            "$id": f"https://wanttoknow.info/schemas/{schema_rel}",
            "title": " ".join(x.capitalize() for x in dataset_id.split("-")),
            "description": "DRAFT inferred schema generated from observed WantToKnow.info data. Review before treating as canonical.",
            **body,
        }
        dump(output / schema_name, schema_doc)
        file_refs = sorted({r for f in files for r in refs.get(posix(f), [])})
        datasets.append({
            "id": dataset_id,
            "role": "role",
            "role_suggestion": role,
            "role_suggestion_reasons": reasons,
            "schema": schema_rel,
            "files": [posix(x) for x in sorted(files)],
            "formats": sorted({x.suffix.lower().lstrip(".") for x in files}),
            "file_scan": scans,
            "referenced_by": file_refs,
            "ambiguity_count": len(local_amb),
        })
        all_amb.extend(local_amb)

    native_rows = [{
        "path": posix(rel),
        "suffix": rel.suffix.lower(),
        "bytes": (repo / rel).stat().st_size,
        "recommended_contract": native_contract(rel.suffix.lower()),
    } for rel in native]

    registry = {
        "version": 1,
        "schema_dialect": DRAFT,
        "generated_directory": posix(output.relative_to(repo)),
        "source_roots": roots,
        "datasets": datasets,
        "unsupported_artifacts": native_rows,
    }
    dump(output / "registry.json", registry)
    dump(output / "ambiguities.json", all_amb)
    dump(output / "unsupported-artifacts.json", native_rows)
    (output / "README.md").write_text(readme(registry), encoding="utf-8")

    errors = [x for d in datasets for x in d["file_scan"] if "error" in x]
    print("Schema inventory complete.")
    print(f"Structured dataset groups: {len(datasets):,}")
    print(f"Ambiguities/warnings:      {len(all_amb):,}")
    print(f"Native/binary artifacts:   {len(native_rows):,}")
    print(f"Output:                    {output}")
    if errors:
        print("\nWARNING: scan errors:")
        for x in errors:
            print(f"  {x['path']}: {x['error']}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
