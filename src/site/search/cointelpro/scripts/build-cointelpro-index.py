#!/usr/bin/env python3
r"""
Build the self-contained COINTELPRO browser-search index from the local
post-MinerU baseline JSONL.

Default input:
  C:\datasources\cointelpro-set\enriched\
    cointelpro_pages_search_baseline_v1.jsonl.gz

Outputs:
  assets/data/cointelpro_page_index.jsonl
  assets/data/cointelpro_manifest.json
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def iter_jsonl(path: Path):
    with open_text(path) as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON at {path}:{line_number}: {exc}"
                ) from exc


def normalize_record(record: dict) -> dict:
    page_id = int(record["page_id"])
    page_key = str(record.get("page_key") or f"{page_id:05d}")
    document_id = str(record.get("document_id") or "")
    document_page_number = int(record.get("document_page_number") or 0)

    image_path = str(record.get("image") or f"web/pages/{page_key}.jpg")
    thumb_path = str(record.get("thumbnail") or f"thumbs/{page_key}-thumb.jpg")

    text = (
        record.get("diplomatic_text")
        or record.get("text")
        or ""
    )

    years = record.get("year_mentions") or []
    years = sorted(
        {
            int(year)
            for year in years
            if str(year).isdigit()
        }
    )

    needs_review = bool(record.get("needs_review", False))
    redaction_count = int(record.get("redaction_count") or 0)

    return {
        "record_id": page_key,
        "page_id": page_id,
        "page_key": page_key,
        "document_id": document_id,
        "document_page_number": document_page_number,
        "source_filename": Path(image_path).name,
        "thumbnail_filename": Path(thumb_path).name,
        "source_relative_path": record.get("source_relative_path"),
        "text": text,
        "year_mentions": years,
        "transcription_status": (
            "needs_review" if needs_review else "usable"
        ),
        "review_reasons": record.get("review_reasons") or [],
        "redaction_count": redaction_count,
    }


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--source",
        type=Path,
        default=Path(
            r"C:\datasources\cointelpro-set\enriched"
            r"\cointelpro_pages_search_baseline_v1.jsonl.gz"
        ),
        help="Source page JSONL or JSONL.GZ",
    )

    parser.add_argument(
        "--app-root",
        type=Path,
        default=Path(
            r"C:\datasources\wanttoknow-site\src\site\search\cointelpro"
        ),
        help="COINTELPRO search app root",
    )

    args = parser.parse_args()

    source = args.source
    app_root = args.app_root
    data_dir = app_root / "assets" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    if not source.exists():
        raise FileNotFoundError(source)

    output_index = data_dir / "cointelpro_page_index.jsonl"
    output_manifest = data_dir / "cointelpro_manifest.json"

    page_ids = set()
    page_keys = set()
    documents = set()

    counts = {
        "pages": 0,
        "documents": 0,
        "pages_with_year_mentions": 0,
        "pages_with_redactions": 0,
        "probable_redaction_regions": 0,
        "pages_needing_review": 0,
    }

    with output_index.open("w", encoding="utf-8", newline="\n") as out:
        for raw in iter_jsonl(source):
            record = normalize_record(raw)

            page_id = record["page_id"]
            page_key = record["page_key"]

            if page_id in page_ids:
                raise ValueError(f"Duplicate page_id: {page_id}")

            if page_key in page_keys:
                raise ValueError(f"Duplicate page_key: {page_key}")

            page_ids.add(page_id)
            page_keys.add(page_key)

            if record["document_id"]:
                documents.add(record["document_id"])

            counts["pages"] += 1

            if record["year_mentions"]:
                counts["pages_with_year_mentions"] += 1

            if record["redaction_count"] > 0:
                counts["pages_with_redactions"] += 1
                counts["probable_redaction_regions"] += record["redaction_count"]

            if record["transcription_status"] == "needs_review":
                counts["pages_needing_review"] += 1

            out.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )

    if page_ids:
        expected = set(range(min(page_ids), max(page_ids) + 1))
        missing = sorted(expected - page_ids)
        if missing:
            raise ValueError(
                f"Canonical page IDs are not contiguous. "
                f"First missing IDs: {missing[:20]}"
            )

    counts["documents"] = len(documents)

    manifest = {
        "dataset": {
            "id": "cointelpro-page-search",
            "title": "COINTELPRO Archive Page Search",
            "version": "1.0.0",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "site_path": "/search/cointelpro/",
            "primary_identifier": "page_id",
            "description": (
                "Client-side page-level transcription index for the "
                "WantToKnow.info COINTELPRO search application."
            ),
        },
        "counts": counts,
        "files": {
            "page_index": {
                "filename": "assets/data/cointelpro_page_index.jsonl",
                "media_type": "application/x-ndjson",
                "record_count": counts["pages"],
                "size_bytes": output_index.stat().st_size,
                "sha256": sha256_file(output_index),
            },
            "thumbnails": {
                "directory": "thumbs/",
                "format": "image/jpeg",
                "max_dimension_pixels": 360,
            },
            "images": {
                "directory": "images/",
                "format": "image/jpeg",
                "max_long_side_pixels": 1575,
            },
        },
        "page_schema": {
            "record_id": "Stable zero-padded page key",
            "page_id": "Permanent integer page identifier",
            "page_key": "Zero-padded page filename key",
            "document_id": "Stable source-document identifier",
            "document_page_number": "Page number within source document",
            "source_filename": "Matching optimized JPEG filename",
            "thumbnail_filename": "Matching JPEG thumbnail filename",
            "source_relative_path": "Original source-document relative path",
            "text": "MinerU transcription with probable-redaction markers",
            "year_mentions": "Years detected during local processing",
            "transcription_status": "usable or needs_review",
            "review_reasons": "Quality-control review flags",
            "redaction_count": "Number of probable redaction regions",
        },
        "provenance": {
            "source": "FBI Vault COINTELPRO collection",
            "source_url": "https://vault.fbi.gov/cointel-pro",
            "dataset_url": (
                "https://huggingface.co/datasets/"
                "peers-ai/cointelpro-fbi-vault-mineru-archive"
            ),
        },
    }

    output_manifest.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(f"Source:    {source}")
    print(f"Pages:     {counts['pages']:,}")
    print(f"Documents: {counts['documents']:,}")
    print(f"Index:     {output_index}")
    print(
        f"Index MB:  {output_index.stat().st_size / 1024**2:.2f}"
    )
    print(f"Manifest:  {output_manifest}")


if __name__ == "__main__":
    main()
