#!/usr/bin/env python3
"""
Audit WantToKnow.info article data before generating static article pages.

Run:
    python /mnt/c/datasources/wanttoknow-site/scripts/audit-article-data.py

This script does not modify any files.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "src" / "site"

INDEX_CANDIDATES = [
    SITE / "data" / "article-index.jsonl",
    SITE / "assets" / "data" / "article-index.jsonl",
]

FULL_JSONL_CANDIDATES = [
    SITE / "data" / "wtk_articles_master.jsonl",
    SITE / "data" / "articles.jsonl",
    SITE / "data" / "article-data.jsonl",
    SITE / "assets" / "data" / "articles.jsonl",
]

MASTER_CSV_CANDIDATES = [
    SITE / "data" / "wtk_articles_master.csv",
    ROOT / "wtk_articles_master.csv",
    ROOT / "data" / "wtk_articles_master.csv",
]


def first_existing(paths):
    for path in paths:
        if path.exists():
            return path
    return None


def preview_jsonl(path: Path, count: int = 3):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if len(rows) >= count:
                break
    return rows


def print_record(record, indent="  "):
    for key in sorted(record):
        value = record[key]
        if isinstance(value, str) and len(value) > 180:
            value = value[:177] + "..."
        print(f"{indent}{key}: {value!r}")


def main():
    print("=" * 78)
    print("WantToKnow.info article data audit")
    print("=" * 78)

    index_path = first_existing(INDEX_CANDIDATES)
    full_path = first_existing(FULL_JSONL_CANDIDATES)
    csv_path = first_existing(MASTER_CSV_CANDIDATES)

    print("\nFILES")
    print(f"  article index : {index_path or 'NOT FOUND'}")
    print(f"  full JSONL    : {full_path or 'NOT FOUND'}")
    print(f"  master CSV    : {csv_path or 'NOT FOUND'}")

    if index_path:
        rows = preview_jsonl(index_path)
        print("\nARTICLE INDEX")
        if rows:
            print("  keys:")
            print("   ", ", ".join(sorted(rows[0].keys())))
            for i, row in enumerate(rows, 1):
                print(f"\n  sample {i}:")
                print_record(row, indent="    ")

    if full_path:
        rows = preview_jsonl(full_path)
        print("\nFULL ARTICLE JSONL")
        if rows:
            print("  keys:")
            print("   ", ", ".join(sorted(rows[0].keys())))
            for i, row in enumerate(rows, 1):
                print(f"\n  sample {i}:")
                print_record(row, indent="    ")

    if csv_path:
        print("\nMASTER CSV")
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="|")
            print("  columns:")
            print("   ", ", ".join(reader.fieldnames or []))
            for i, row in enumerate(reader, 1):
                if i > 3:
                    break
                print(f"\n  sample {i}:")
                print_record(row, indent="    ")

    print("\nFIELDS NEEDED FOR ARTICLE GENERATION")
    wanted = [
        "id / article_id",
        "slug",
        "title",
        "publication date",
        "date posted to WTK",
        "publisher",
        "priority",
        "tags",
        "related article IDs",
        "source URL",
        "summary Markdown",
        "note Markdown",
        "image filename/path",
        "image caption",
    ]
    for item in wanted:
        print(f"  - {item}")

    print("\nNo files were changed.")


if __name__ == "__main__":
    main()
