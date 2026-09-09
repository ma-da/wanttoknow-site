#!/usr/bin/env python3
"""
Remove deferred WingMakers material from the WantToKnow.info phase-1 corpus.

Default behavior is DRY RUN.
Use --apply to write changes.

What it changes
---------------
Canonical:
  src/site/data/corpus/pages-v1.jsonl
      Removes PageRecords whose canonical path/directory is under
      /speculation/wingmakers/.

Derived outputs:
  Deletes these so they can be rebuilt cleanly:
      src/site/data/corpus/document-chunks-v1.jsonl
      src/site/data/corpus/youtube-search-chunks-v1.jsonl
      src/site/data/corpus/ref-registry-v1.jsonl
      reports/build/search-corpus-build.json

Generated static WingMakers output:
  Removes:
      src/site/speculation/wingmakers/

Reports:
  reports/migration/wingmakers-phase1-removal.json

The raw/deferred source material is NOT deleted from unrelated archival/raw
locations. This script only removes WingMakers from the phase-1 site corpus
and generated site output.
"""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json
import shutil
import sys


DEFAULT_SITE_ROOT = Path("/mnt/c/datasources/wanttoknow-site")
WINGMAKERS_PREFIX = "/speculation/wingmakers"


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_site_path(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\\", "/").strip()

    if not text:
        return ""

    if not text.startswith("/"):
        text = "/" + text

    while "//" in text:
        text = text.replace("//", "/")

    return text.rstrip("/").casefold()


def is_wingmakers_page(row: dict[str, Any]) -> bool:
    """
    Match only canonical WingMakers pages by site path/directory.

    We deliberately do NOT remove ordinary pages merely because their prose
    mentions the word "WingMakers".
    """
    path = normalize_site_path(row.get("path"))
    directory = normalize_site_path(row.get("directory"))

    prefix = WINGMAKERS_PREFIX.casefold()

    return (
        path == prefix
        or path.startswith(prefix + "/")
        or directory == prefix
        or directory.startswith(prefix + "/")
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path}:{line_number}: invalid JSON: {exc}"
                ) from exc

            if not isinstance(row, dict):
                raise RuntimeError(
                    f"{path}:{line_number}: row is not a JSON object."
                )

            rows.append(row)

    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            f.write("\n")

    temp.replace(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_args():
    parser = ArgumentParser(
        description=(
            "Remove WingMakers material from the phase-1 site corpus."
        )
    )

    parser.add_argument(
        "--site-root",
        type=Path,
        default=DEFAULT_SITE_ROOT,
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write/delete files. Without this flag, dry run only.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.site_root

    corpus = root / "src" / "site" / "data" / "corpus"

    pages_path = corpus / "pages-v1.jsonl"

    derived_files = [
        corpus / "document-chunks-v1.jsonl",
        corpus / "youtube-search-chunks-v1.jsonl",
        corpus / "ref-registry-v1.jsonl",
        root / "reports" / "build" / "search-corpus-build.json",
    ]

    generated_wingmakers_dir = (
        root
        / "src"
        / "site"
        / "speculation"
        / "wingmakers"
    )

    report_path = (
        root
        / "reports"
        / "migration"
        / "wingmakers-phase1-removal.json"
    )

    if not pages_path.exists():
        raise RuntimeError(
            f"Missing canonical PageRecord corpus: {pages_path}"
        )

    pages = load_jsonl(pages_path)

    removed = [
        row
        for row in pages
        if is_wingmakers_page(row)
    ]

    kept = [
        row
        for row in pages
        if not is_wingmakers_page(row)
    ]

    removed_ids = [
        str(row.get("id"))
        for row in removed
    ]

    removed_paths = [
        str(row.get("path"))
        for row in removed
    ]

    existing_derived = [
        str(path)
        for path in derived_files
        if path.exists()
    ]

    generated_exists = generated_wingmakers_dir.exists()

    report = {
        "operation": "wingmakers-phase1-removal",
        "mode": "apply" if args.apply else "dry-run",
        "created_at": now_iso(),
        "wingmakers_prefix": WINGMAKERS_PREFIX,
        "canonical_pages_before": len(pages),
        "wingmakers_pages_found": len(removed),
        "canonical_pages_after": len(kept),
        "removed_page_ids": removed_ids,
        "removed_paths": removed_paths,
        "derived_files_to_reset": existing_derived,
        "generated_wingmakers_directory": str(
            generated_wingmakers_dir
        ),
        "generated_wingmakers_directory_exists": generated_exists,
        "canonical_pages_file": str(pages_path),
    }

    print()
    print("======================================")
    print("WINGMAKERS PHASE-1 REMOVAL")
    print("======================================")
    print(
        f"Mode:                     "
        f"{'APPLY' if args.apply else 'DRY RUN'}"
    )
    print(f"Canonical pages before:   {len(pages):,}")
    print(f"WingMakers pages found:   {len(removed):,}")
    print(f"Canonical pages after:    {len(kept):,}")
    print()
    print("Matched PageRecords:")

    for row in removed:
        print(
            f"  {row.get('id')} | {row.get('path')}"
        )

    print()
    print("Derived outputs to reset:")

    if existing_derived:
        for path in existing_derived:
            print(f"  {path}")
    else:
        print("  none currently present")

    print()
    print(
        "Generated WingMakers directory: "
        f"{generated_wingmakers_dir}"
    )
    print(
        f"  {'present' if generated_exists else 'not present'}"
    )

    if not removed:
        print()
        print(
            "No canonical WingMakers PageRecords matched. "
            "Nothing will be changed."
        )

        write_json(report_path, report)
        return

    if not args.apply:
        print()
        print("DRY RUN ONLY — no corpus files changed.")
        print()
        print("If the matched list is correct, run:")
        print(
            "  python scripts/remove-wingmakers-phase1.py --apply"
        )
        return

    # ------------------------------------------------------------------
    # Apply canonical removal
    # ------------------------------------------------------------------

    write_jsonl(
        pages_path,
        kept,
    )

    # Reset derived outputs. They must be rebuilt from the cleaned corpus.
    deleted_files = []

    for path in derived_files:
        if path.exists():
            path.unlink()
            deleted_files.append(str(path))

    # Remove generated static WingMakers pages/index if present.
    removed_generated_dir = False

    if generated_wingmakers_dir.exists():
        shutil.rmtree(
            generated_wingmakers_dir
        )
        removed_generated_dir = True

    report["deleted_derived_files"] = deleted_files
    report["removed_generated_directory"] = removed_generated_dir
    report["applied_at"] = now_iso()

    write_json(
        report_path,
        report,
    )

    print()
    print("======================================")
    print("WINGMAKERS REMOVAL COMPLETE")
    print("======================================")
    print(
        f"Removed canonical pages:  {len(removed):,}"
    )
    print(
        f"Remaining canonical pages:{len(kept):,}"
    )
    print(
        f"Reset derived files:      {len(deleted_files):,}"
    )
    print(
        f"Removed generated dir:    "
        f"{'yes' if removed_generated_dir else 'no'}"
    )
    print()
    print(f"Report: {report_path}")
    print()
    print("Next rebuild:")
    print("  python scripts/build-search-corpus.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        print()
        print(
            "WINGMAKERS REMOVAL FAILED",
            file=sys.stderr,
        )
        print(
            str(exc),
            file=sys.stderr,
        )
        raise
