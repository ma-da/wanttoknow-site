from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from .article_store import (
    connect,
    create_schema,
    export_master,
    import_master,
    verify_roundtrip,
)


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def parse_args() -> argparse.Namespace:
    root = default_repo_root()
    parser = argparse.ArgumentParser(
        description="Create the WantToKnow admin article SQLite database and verify JSONL round-trip fidelity."
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=root / "src/site/data/wtk_articles_master.jsonl",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=root / "backend/var/admin-dev.sqlite3",
    )
    parser.add_argument(
        "--roundtrip",
        type=Path,
        default=root / "backend/var/wtk_articles_roundtrip.jsonl",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing admin database. Does not modify the master JSONL.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    master = args.master.resolve()
    db = args.db.resolve()
    roundtrip = args.roundtrip.resolve()

    if not master.is_file():
        raise SystemExit(f"Master JSONL not found: {master}")

    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        if not args.replace:
            raise SystemExit(
                f"Admin database already exists: {db}\n"
                "Refusing to overwrite it. Re-run with --replace only if that is intentional."
            )
        db.unlink()

    print(f"Master:     {master}")
    print(f"Admin DB:   {db}")
    print(f"Round-trip: {roundtrip}")
    print()

    conn = connect(db)
    try:
        create_schema(conn)
        count = import_master(conn, master)
        exported_count = export_master(conn, roundtrip)
        verified_count, semantic_hash = verify_roundtrip(master, roundtrip)

        db_count = conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        tag_count = conn.execute("SELECT COUNT(*) FROM article_tags").fetchone()[0]
        dirty_count = conn.execute(
            "SELECT COUNT(*) FROM articles WHERE edit_state <> 'clean'"
        ).fetchone()[0]

        try:
            fts_count = conn.execute("SELECT COUNT(*) FROM article_fts").fetchone()[0]
        except sqlite3.OperationalError:
            fts_count = -1

        if not (count == exported_count == verified_count == db_count):
            raise RuntimeError(
                "Count verification failed: "
                f"import={count}, export={exported_count}, "
                f"verify={verified_count}, db={db_count}"
            )
        if dirty_count != 0:
            raise RuntimeError(f"Fresh import unexpectedly contains {dirty_count} dirty articles")

        print("PASS: canonical JSONL imported successfully")
        print(f"PASS: {db_count:,} articles in SQLite")
        print(f"PASS: {tag_count:,} article/tag relationships indexed")
        print(f"PASS: {fts_count:,} articles available to FTS5 search")
        print(f"PASS: {exported_count:,} articles exported")
        print("PASS: exported JSONL is semantically identical to the canonical master")
        print(f"Semantic SHA-256: {semantic_hash}")
        print()
        print("The canonical master was read only; it was not modified.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
