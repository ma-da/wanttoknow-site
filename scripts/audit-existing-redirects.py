#!/usr/bin/env python3

import csv
import json
from collections import defaultdict
from urllib.parse import urlsplit

REDIRECTS = "src/site/data/legacy-redirects.csv"
MASTER = "src/site/data/wtk_articles_master.jsonl"

# Existing redirect CSV
rows = list(csv.DictReader(open(REDIRECTS, encoding="utf-8")))

by_old = defaultdict(list)

for row in rows:
    by_old[row["old_path"]].append(row)

duplicate_paths = {
    path: items
    for path, items in by_old.items()
    if len(items) > 1
}

conflicts = {}

for path, items in duplicate_paths.items():
    targets = {x["new_path"] for x in items}
    if len(targets) > 1:
        conflicts[path] = items

article_csv_paths = {
    row["old_path"]
    for row in rows
    if row["type"] == "article"
}

# Master article legacy URLs
master_rows = [
    json.loads(line)
    for line in open(MASTER, encoding="utf-8")
    if line.strip()
]

master_paths = []

for row in master_rows:
    legacy = row.get("legacy_url")
    if legacy:
        master_paths.append(urlsplit(legacy).path)

master_unique = set(master_paths)

missing_from_csv = sorted(master_unique - article_csv_paths)
extra_in_csv = sorted(article_csv_paths - master_unique)

print("=== EXISTING REDIRECT CSV ===")
print("rows:", len(rows))
print("unique old paths:", len(by_old))
print("duplicate old paths:", len(duplicate_paths))
print("conflicting duplicate targets:", len(conflicts))

print()
print("=== ARTICLE COMPARISON ===")
print("master legacy records:", len(master_paths))
print("master unique legacy paths:", len(master_unique))
print("CSV unique article paths:", len(article_csv_paths))
print("master paths missing from CSV:", len(missing_from_csv))
print("CSV article paths absent from master:", len(extra_in_csv))

print()
print("=== MISSING FROM CSV ===")
for path in missing_from_csv:
    print(path)

print()
print("=== EXTRA IN CSV ===")
for path in extra_in_csv:
    print(path)

print()
print("=== CONFLICTING CSV DUPLICATES ===")
for path, items in conflicts.items():
    print(path)
    for item in items:
        print("   ", item["new_path"])
