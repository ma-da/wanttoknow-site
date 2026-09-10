#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime
from pathlib import Path

def norm_id(v):
    return str(v).strip().removesuffix(".0")

def iso_date(v):
    v = str(v).strip()
    d = datetime.strptime(v, "%Y-%m-%d")
    if d.strftime("%Y-%m-%d") != v:
        raise ValueError(f"Bad date: {v}")
    return v

def load_posted(posted_path):
    out = {}
    with posted_path.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f, delimiter="|")
        if not {"ArticleId", "posted"} <= set(r.fieldnames or []):
            raise ValueError("Article-Posted.csv must contain ArticleId|posted")
        for row in r:
            aid = norm_id(row["ArticleId"])
            if aid in out:
                raise ValueError(f"Duplicate ArticleId in posted CSV: {aid}")
            out[aid] = iso_date(row["posted"])
    return out

def read_jsonl(path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception as e:
                    raise ValueError(f"Bad JSON in {path.name} line {n}") from e
    return rows

def add_after(d, key, value, after):
    out = {}
    inserted = False
    for k, v in d.items():
        if k == key:
            continue
        out[k] = v
        if k == after:
            out[key] = value
            inserted = True
    if not inserted:
        out[key] = value
    return out

def parse_args():
    parser = argparse.ArgumentParser(
        description="Apply legacy posted dates to WantToKnow.info article datasets."
    )
    parser.add_argument(
        "--site-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="WantToKnow.info repository root.",
    )
    parser.add_argument(
        "--posted-csv",
        type=Path,
        required=True,
        help="Source Article-Posted.csv containing ArticleId|posted.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    data = args.site_root / "src" / "site" / "data"
    posted_path = args.posted_csv.expanduser().resolve()

    master_csv = data / "wtk_articles_master.csv"
    master_jsonl = data / "wtk_articles_master.jsonl"
    index_jsonl = data / "article-index.jsonl"

    required = [posted_path, master_csv, master_jsonl, index_jsonl]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Required input file(s) missing:\n  " + "\n  ".join(missing)
        )

    posted = load_posted(posted_path)

    with master_csv.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.DictReader(f, delimiter="|")
        fields = list(r.fieldnames or [])
        csv_rows = list(r)

    if "posted_date" not in fields:
        pos = fields.index("publication_date") + 1
        fields.insert(pos, "posted_date")

    csv_ids = set()
    for row in csv_rows:
        aid = norm_id(row["article_id"])
        csv_ids.add(aid)
        if aid not in posted:
            raise ValueError(f"Missing posted date for master CSV article {aid}")
        row["posted_date"] = posted[aid]

    master_rows = read_jsonl(master_jsonl)
    master_ids = set()
    new_master = []
    for row in master_rows:
        aid = norm_id(row["article_id"])
        master_ids.add(aid)
        if aid not in posted:
            raise ValueError(f"Missing posted date for master JSONL article {aid}")
        new_master.append(add_after(row, "posted_date", posted[aid], "publication_date"))

    index_rows = read_jsonl(index_jsonl)
    index_ids = set()
    new_index = []
    for row in index_rows:
        aid = norm_id(row["id"])
        index_ids.add(aid)
        if aid not in posted:
            raise ValueError(f"Missing posted date for index article {aid}")
        new_index.append(add_after(row, "posted_date", posted[aid], "date"))

    if not (csv_ids == master_ids == index_ids):
        raise ValueError(
            "The new-site Article ID sets do not match across "
            "master CSV, master JSONL, and article index."
        )

    missing = csv_ids - set(posted)
    if missing:
        preview = ", ".join(sorted(missing, key=int)[:20])
        raise ValueError(
            f"{len(missing)} new-site articles have no posted date. "
            f"First IDs: {preview}"
        )

    extra = set(posted) - csv_ids
    if extra:
        preview = ", ".join(sorted(extra, key=int)[:20])
        print(
            f"NOTE: {len(extra)} legacy posted-date rows are not present "
            f"in the cleaned new-site dataset and will be ignored. "
            f"First IDs: {preview}"
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for p in (master_csv, master_jsonl, index_jsonl):
        backup = p.with_name(p.name + f".bak-{stamp}")
        shutil.copy2(p, backup)
        print("Backup:", backup)

    tmp_csv = master_csv.with_name(master_csv.name + ".tmp")
    with tmp_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="|", lineterminator="\n")
        w.writeheader()
        w.writerows(csv_rows)

    def write_jsonl(path, rows):
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    tmp_master = master_jsonl.with_name(master_jsonl.name + ".tmp")
    tmp_index = index_jsonl.with_name(index_jsonl.name + ".tmp")
    write_jsonl(tmp_master, new_master)
    write_jsonl(tmp_index, new_index)

    tmp_csv.replace(master_csv)
    tmp_master.replace(master_jsonl)
    tmp_index.replace(index_jsonl)

    print()
    print(f"SUCCESS: added posted_date to {len(posted):,} articles.")
    print("Stored format: YYYY-MM-DD")

if __name__ == "__main__":
    main()
