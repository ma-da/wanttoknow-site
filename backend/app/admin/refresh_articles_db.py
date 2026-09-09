from __future__ import annotations

import argparse
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .article_query import admin_db_path, default_repo_root
from .article_store import create_schema, export_master, import_master, verify_roundtrip
from .image_staging import clear_all_staged_images, count_staged_images
from .article_withdrawal import cancel_all_pending_withdrawals, count_pending_withdrawals


def parse_args() -> argparse.Namespace:
    root = default_repo_root()
    parser = argparse.ArgumentParser(
        description=(
            "Refresh the complete admin articles working copy from the canonical master JSONL "
            "while preserving admin sessions and existing revision history."
        )
    )
    parser.add_argument(
        "--master",
        type=Path,
        default=root / "src/site/data/wtk_articles_master.jsonl",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=admin_db_path(),
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=root / "backend/var/backups",
    )
    parser.add_argument(
        "--discard-drafts",
        action="store_true",
        help="Discard modified/new SQLite article state and replace it with the master JSONL.",
    )
    return parser.parse_args()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _backup_database(conn: sqlite3.Connection, backup_path: Path) -> None:
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(backup_path) as dest:
        conn.backup(dest)


def _refresh_articles(current: sqlite3.Connection, staged: sqlite3.Connection) -> int:
    incoming = staged.execute("SELECT * FROM articles ORDER BY source_order").fetchall()
    incoming_tags = staged.execute(
        "SELECT article_id, tag FROM article_tags ORDER BY article_id, tag"
    ).fetchall()
    staged_state = staged.execute("SELECT key, value FROM admin_state").fetchall()

    with current:
        # Free every positive source_order value before assigning the new canonical order.
        current.execute("UPDATE articles SET source_order = -source_order")
        current.execute("CREATE TEMP TABLE IF NOT EXISTS refresh_article_ids(article_id INTEGER PRIMARY KEY)")
        current.execute("DELETE FROM refresh_article_ids")

        for row in incoming:
            article_id = row["article_id"]
            current.execute(
                "INSERT INTO refresh_article_ids(article_id) VALUES (?)",
                (article_id,),
            )
            exists = current.execute(
                "SELECT 1 FROM articles WHERE article_id = ?",
                (article_id,),
            ).fetchone()

            values = (
                row["source_order"], row["slug"], row["path"], row["url"],
                row["legacy_url"], row["title"], row["publication_date"],
                row["posted_date"], row["publication_group"], row["publication_name"],
                row["publication_detail"], row["publication_raw"], row["source_url"],
                row["summary_markdown"], row["note_markdown"], row["description_markdown"],
                row["tags_json"], row["related_articles_json"], row["priority"],
                row["image_filename"], row["image_path"], row["image_caption_markdown"],
                row["image_caption_text"], row["qc_flags_json"], row["canonical_hash"],
            )

            if exists:
                current.execute(
                    """
                    UPDATE articles SET
                        source_order = ?, slug = ?, path = ?, url = ?, legacy_url = ?, title = ?,
                        publication_date = ?, posted_date = ?, publication_group = ?, publication_name = ?,
                        publication_detail = ?, publication_raw = ?, source_url = ?, summary_markdown = ?,
                        note_markdown = ?, description_markdown = ?, tags_json = ?, related_articles_json = ?,
                        priority = ?, image_filename = ?, image_path = ?, image_caption_markdown = ?,
                        image_caption_text = ?, qc_flags_json = ?, canonical_hash = ?,
                        edit_state = 'clean', workflow_state = 'published', active_batch_id = NULL,
                        admin_updated_at = NULL, admin_updated_by = NULL
                    WHERE article_id = ?
                    """,
                    (*values, article_id),
                )
            else:
                current.execute(
                    """
                    INSERT INTO articles(
                        article_id, source_order, slug, path, url, legacy_url, title,
                        publication_date, posted_date, publication_group, publication_name,
                        publication_detail, publication_raw, source_url, summary_markdown,
                        note_markdown, description_markdown, tags_json, related_articles_json,
                        priority, image_filename, image_path, image_caption_markdown,
                        image_caption_text, qc_flags_json, canonical_hash,
                        edit_state, workflow_state
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'clean', 'published'
                    )
                    """,
                    (article_id, *values),
                )

        # Articles removed from the canonical master are removed from the working copy.
        current.execute(
            "DELETE FROM articles WHERE article_id NOT IN (SELECT article_id FROM refresh_article_ids)"
        )

        current.execute("DELETE FROM article_tags")
        current.executemany(
            "INSERT INTO article_tags(article_id, tag) VALUES (?, ?)",
            ((row["article_id"], row["tag"]) for row in incoming_tags),
        )

        for row in staged_state:
            current.execute(
                """
                INSERT INTO admin_state(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (row["key"], row["value"]),
            )

    return len(incoming)


def main() -> int:
    args = parse_args()
    master = args.master.expanduser().resolve()
    db = args.db.expanduser().resolve()
    backup_dir = args.backup_dir.expanduser().resolve()

    if not master.is_file():
        raise SystemExit(f"Master JSONL not found: {master}")
    if not db.is_file():
        raise SystemExit(
            f"Admin DB not found: {db}\n"
            "Create it first with: python3 -m backend.app.admin.init_articles_db"
        )

    current = _connect(db)
    try:
        dirty_count = current.execute(
            "SELECT COUNT(*) FROM articles WHERE edit_state <> 'clean'"
        ).fetchone()[0]
        staged_image_count = count_staged_images(current)
        pending_withdrawal_count = count_pending_withdrawals(current)
        if (dirty_count or staged_image_count or pending_withdrawal_count) and not args.discard_drafts:
            raise SystemExit(
                "REFUSED: admin working state contains unpublished changes.\n"
                f"Article edits/new records: {dirty_count}\n"
                f"Staged images: {staged_image_count}\n"
                f"Pending withdrawals: {pending_withdrawal_count}\n"
                "Publish/reconcile them first, or re-run with --discard-drafts only if losing those changes is intentional."
            )

        with tempfile.TemporaryDirectory(prefix="wtk-admin-refresh-") as temp_dir:
            stage_path = Path(temp_dir) / "staged.sqlite3"
            staged = _connect(stage_path)
            try:
                create_schema(staged)
                staged_count = import_master(staged, master)
            finally:
                staged.close()

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
            backup_path = backup_dir / f"admin-dev-before-refresh-{timestamp}.sqlite3"
            _backup_database(current, backup_path)

            staged = _connect(stage_path)
            try:
                refreshed_count = _refresh_articles(current, staged)
            finally:
                staged.close()

            discarded_images = 0
            cancelled_withdrawals = 0
            if args.discard_drafts:
                discarded_images = clear_all_staged_images(current)
                cancelled_withdrawals = cancel_all_pending_withdrawals(
                    current,
                    cancelled_by="refresh_articles_db --discard-drafts",
                )

            verify_path = Path(temp_dir) / "verify.jsonl"
            exported_count = export_master(current, verify_path)
            verified_count, semantic_hash = verify_roundtrip(master, verify_path)

            if not (staged_count == refreshed_count == exported_count == verified_count):
                raise RuntimeError(
                    "Refresh count mismatch: "
                    f"stage={staged_count}, refreshed={refreshed_count}, "
                    f"export={exported_count}, verify={verified_count}"
                )

        print(f"PASS: refreshed {refreshed_count:,} articles from canonical master")
        print("PASS: refreshed SQLite is semantically identical to master JSONL")
        print(f"Semantic SHA-256: {semantic_hash}")
        print(f"Backup: {backup_path}")
        print("Admin login sessions were preserved.")
        print("Article revision history for articles that still exist was preserved.")
        if args.discard_drafts and discarded_images:
            print(f"Discarded staged images: {discarded_images}")
        if args.discard_drafts and cancelled_withdrawals:
            print(f"Cancelled pending withdrawals: {cancelled_withdrawals}")
        return 0
    finally:
        current.close()


if __name__ == "__main__":
    raise SystemExit(main())
