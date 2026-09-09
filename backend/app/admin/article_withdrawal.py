from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .article_store import article_hash, row_to_article, utc_now
from .article_workflow import ensure_open_batch

REASON_CODES = {
    "takedown": "Takedown request",
    "source_reliability": "Source reliability",
    "duplicate": "Duplicate",
    "other": "Other",
}




def _has_staged_image(conn: sqlite3.Connection, article_id: int) -> bool:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'article_image_staging'"
    ).fetchone()
    if table is None:
        return False
    return conn.execute(
        "SELECT 1 FROM article_image_staging WHERE article_id = ?",
        (article_id,),
    ).fetchone() is not None


def _default_master_path() -> Path:
    return Path(__file__).resolve().parents[3] / "src/site/data/wtk_articles_master.jsonl"


def ensure_withdrawal_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS article_withdrawals (
            withdrawal_id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'removed', 'cancelled')),
            requested_at TEXT NOT NULL,
            requested_by TEXT NOT NULL,
            reason_code TEXT NOT NULL,
            reason_text TEXT NOT NULL DEFAULT '',
            redirect_path TEXT NOT NULL DEFAULT '',
            canonical_article_json TEXT NOT NULL,
            working_article_json TEXT NOT NULL,
            canonical_hash TEXT NOT NULL,
            removed_at TEXT,
            removed_by TEXT,
            cancelled_at TEXT,
            cancelled_by TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_article_withdrawals_pending
            ON article_withdrawals(article_id)
            WHERE status = 'pending';

        CREATE INDEX IF NOT EXISTS idx_article_withdrawals_status
            ON article_withdrawals(status, requested_at DESC);

        CREATE INDEX IF NOT EXISTS idx_article_withdrawals_article
            ON article_withdrawals(article_id, withdrawal_id DESC);
        """
    )


def withdrawal_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'article_withdrawals'"
    ).fetchone()
    return row is not None


def _row_to_withdrawal(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "withdrawal_id": int(row["withdrawal_id"]),
        "article_id": str(row["article_id"]),
        "status": row["status"],
        "requested_at": row["requested_at"],
        "requested_by": row["requested_by"],
        "reason_code": row["reason_code"],
        "reason_label": REASON_CODES.get(row["reason_code"], row["reason_code"]),
        "reason_text": row["reason_text"],
        "redirect_path": row["redirect_path"],
        "removed_at": row["removed_at"],
        "removed_by": row["removed_by"],
        "cancelled_at": row["cancelled_at"],
        "cancelled_by": row["cancelled_by"],
    }


def pending_withdrawal_for_article(conn: sqlite3.Connection, article_id: int) -> dict[str, Any] | None:
    if not withdrawal_table_exists(conn):
        return None
    row = conn.execute(
        """
        SELECT *
        FROM article_withdrawals
        WHERE article_id = ? AND status = 'pending'
        ORDER BY withdrawal_id DESC
        LIMIT 1
        """,
        (article_id,),
    ).fetchone()
    return _row_to_withdrawal(row)


def count_pending_withdrawals(conn: sqlite3.Connection) -> int:
    if not withdrawal_table_exists(conn):
        return 0
    return int(
        conn.execute("SELECT COUNT(*) FROM article_withdrawals WHERE status = 'pending'").fetchone()[0]
    )


def _load_canonical_article(article_id: int, master_path: Path | None = None) -> dict[str, Any]:
    path = (master_path or _default_master_path()).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Canonical master JSONL not found: {path}")

    target = str(article_id)
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                article = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in canonical master on line {line_no}: {exc}") from exc
            if str(article.get("article_id", "")) == target:
                return article
    raise ValueError(f"Article {article_id} is not present in the canonical master JSONL")


def _normalize_redirect_path(value: str, current_path: str) -> str:
    redirect = value.strip()
    if not redirect:
        return ""
    if not redirect.startswith("/") or redirect.startswith("//"):
        raise ValueError("Replacement path must be a WantToKnow.info path beginning with a single /")
    if "\n" in redirect or "\r" in redirect:
        raise ValueError("Replacement path is invalid")
    if redirect == current_path:
        raise ValueError("Replacement path cannot be the article's current path")
    return redirect


def request_withdrawal(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    reason_code: str,
    reason_text: str,
    redirect_path: str,
    requested_by: str,
    master_path: Path | None = None,
) -> dict[str, Any]:
    ensure_withdrawal_schema(conn)
    row = conn.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,)).fetchone()
    if row is None:
        raise LookupError("Article not found")
    if row["edit_state"] == "new" or not row["canonical_hash"]:
        raise ValueError("Never-published drafts should be deleted, not withdrawn from the site")
    if pending_withdrawal_for_article(conn, article_id) is not None:
        raise ValueError("This article is already scheduled for removal")

    reason_code = reason_code.strip()
    if reason_code not in REASON_CODES:
        raise ValueError("Choose a valid removal reason")
    reason_text = reason_text.strip()
    if reason_code == "other" and not reason_text:
        raise ValueError("Please describe the removal reason when choosing Other")

    working = row_to_article(row)
    canonical = _load_canonical_article(article_id, master_path)
    expected_hash = str(row["canonical_hash"] or "")
    actual_hash = article_hash(canonical)
    if expected_hash and actual_hash != expected_hash:
        raise ValueError(
            "The canonical master and SQLite working copy are out of sync for this article. "
            "Refresh/reconcile before scheduling removal."
        )

    redirect = _normalize_redirect_path(redirect_path, str(canonical.get("path", "")))
    now = utc_now()

    try:
        conn.execute("BEGIN IMMEDIATE")
        batch_id = ensure_open_batch(conn)
        cursor = conn.execute(
            """
            INSERT INTO article_withdrawals(
                article_id, status, requested_at, requested_by,
                reason_code, reason_text, redirect_path,
                canonical_article_json, working_article_json, canonical_hash
            ) VALUES (?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id,
                now,
                requested_by,
                reason_code,
                reason_text,
                redirect,
                json.dumps(canonical, ensure_ascii=False, separators=(",", ":")),
                json.dumps(working, ensure_ascii=False, separators=(",", ":")),
                actual_hash,
            ),
        )
        conn.execute(
            """
            UPDATE articles
            SET workflow_state = 'draft', active_batch_id = ?,
                admin_updated_at = ?, admin_updated_by = ?
            WHERE article_id = ?
            """,
            (batch_id, now, requested_by, article_id),
        )
        conn.execute("UPDATE article_batches SET updated_at = ? WHERE batch_id = ?", (now, batch_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "scheduled": True,
        "article_id": str(article_id),
        "batch_id": batch_id,
        "withdrawal": _row_to_withdrawal(
            conn.execute("SELECT * FROM article_withdrawals WHERE withdrawal_id = ?", (cursor.lastrowid,)).fetchone()
        ),
        "admin": {
            "edit_state": row["edit_state"],
            "workflow_state": "draft",
            "active_batch_id": batch_id,
            "admin_updated_at": now,
            "admin_updated_by": requested_by,
        },
    }


def cancel_withdrawal(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    cancelled_by: str,
) -> dict[str, Any]:
    ensure_withdrawal_schema(conn)
    row = conn.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,)).fetchone()
    if row is None:
        raise LookupError("Article not found")
    pending = conn.execute(
        """
        SELECT * FROM article_withdrawals
        WHERE article_id = ? AND status = 'pending'
        ORDER BY withdrawal_id DESC
        LIMIT 1
        """,
        (article_id,),
    ).fetchone()
    if pending is None:
        raise ValueError("This article is not scheduled for removal")

    now = utc_now()
    remains_draft = row["edit_state"] != "clean" or _has_staged_image(conn, article_id)
    workflow_state = "draft" if remains_draft else "published"
    batch_id = ensure_open_batch(conn) if remains_draft else None

    with conn:
        conn.execute(
            """
            UPDATE article_withdrawals
            SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?
            WHERE withdrawal_id = ?
            """,
            (now, cancelled_by, pending["withdrawal_id"]),
        )
        conn.execute(
            """
            UPDATE articles
            SET workflow_state = ?, active_batch_id = ?,
                admin_updated_at = ?, admin_updated_by = ?
            WHERE article_id = ?
            """,
            (workflow_state, batch_id, now, cancelled_by, article_id),
        )
        if batch_id is not None:
            conn.execute("UPDATE article_batches SET updated_at = ? WHERE batch_id = ?", (now, batch_id))

    return {
        "cancelled": True,
        "article_id": str(article_id),
        "admin": {
            "edit_state": row["edit_state"],
            "workflow_state": workflow_state,
            "active_batch_id": batch_id,
            "admin_updated_at": now,
            "admin_updated_by": cancelled_by,
        },
        "withdrawal": None,
    }


def cancel_all_pending_withdrawals(
    conn: sqlite3.Connection,
    *,
    cancelled_by: str,
) -> int:
    if not withdrawal_table_exists(conn):
        return 0
    now = utc_now()
    with conn:
        cursor = conn.execute(
            """
            UPDATE article_withdrawals
            SET status = 'cancelled', cancelled_at = ?, cancelled_by = ?
            WHERE status = 'pending'
            """,
            (now, cancelled_by),
        )
    return int(cursor.rowcount or 0)
