#!/usr/bin/env python3
import csv, json, shutil
from datetime import datetime
from pathlib import Path

ROOT = Path("/mnt/c/datasources/wanttoknow-site")
DATA = ROOT / "src" / "site" / "data"

POSTED = Path("/mnt/c/datasources/Article-Posted.csv")
MASTER_CSV = DATA / "wtk_articles_master.csv"
MASTER_JSONL = DATA / "wtk_articles_master.jsonl"
INDEX_JSONL = DATA / "article-index.jsonl"

def norm_id(v):
    return str(v).strip().removesuffix(".0")

def iso_date(v):
    v = str(v).strip()
    d = datetime.strptime(v, "%Y-%m-%d")
    if d.strftime("%Y-%m-%d") != v:
        raise ValueError(f"Bad date: {v}")
    return v

def load_posted():
    out = {}
    with POSTED.open("r", encoding="utf-8-sig", newline="") as f:
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

def main():
    posted = load_posted()

    with MASTER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
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

    master_rows = read_jsonl(MASTER_JSONL)
    master_ids = set()
    new_master = []
    for row in master_rows:
        aid = norm_id(row["article_id"])
        master_ids.add(aid)
        if aid not in posted:
            raise ValueError(f"Missing posted date for master JSONL article {aid}")
        new_master.append(add_after(row, "posted_date", posted[aid], "publication_date"))

    index_rows = read_jsonl(INDEX_JSONL)
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
    for p in (MASTER_CSV, MASTER_JSONL, INDEX_JSONL):
        backup = p.with_name(p.name + f".bak-{stamp}")
        shutil.copy2(p, backup)
        print("Backup:", backup)

    tmp_csv = MASTER_CSV.with_name(MASTER_CSV.name + ".tmp")
    with tmp_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="|", lineterminator="\n")
        w.writeheader()
        w.writerows(csv_rows)

    def write_jsonl(path, rows):
        with path.open("w", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    tmp_master = MASTER_JSONL.with_name(MASTER_JSONL.name + ".tmp")
    tmp_index = INDEX_JSONL.with_name(INDEX_JSONL.name + ".tmp")
    write_jsonl(tmp_master, new_master)
    write_jsonl(tmp_index, new_index)

    tmp_csv.replace(MASTER_CSV)
    tmp_master.replace(MASTER_JSONL)
    tmp_index.replace(INDEX_JSONL)

    print()
    print(f"SUCCESS: added posted_date to {len(posted):,} articles.")
    print("Stored format: YYYY-MM-DD")

if __name__ == "__main__":
    main()
