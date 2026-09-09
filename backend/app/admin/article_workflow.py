from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from .article_store import utc_now

ADMIN_TZ = ZoneInfo("America/Chicago")


def _default_batch_name() -> str:
    now = datetime.now(ADMIN_TZ)
    return f"{now.strftime('%B')} {now.day}, {now.year}"


def ensure_open_batch(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT batch_id
        FROM article_batches
        WHERE status = 'open'
        ORDER BY batch_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        batch_id = int(row["batch_id"] if isinstance(row, sqlite3.Row) else row[0])
    else:
        now = utc_now()
        cursor = conn.execute(
            """
            INSERT INTO article_batches(name, status, created_at, updated_at)
            VALUES (?, 'open', ?, ?)
            """,
            (_default_batch_name(), now, now),
        )
        batch_id = int(cursor.lastrowid)

    # Fold any drafts created before batch support into the current open batch.
    conn.execute(
        """
        UPDATE articles
        SET active_batch_id = ?
        WHERE workflow_state IN ('draft', 'ready')
          AND active_batch_id IS NULL
        """,
        (batch_id,),
    )
    return batch_id


def set_article_workflow(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    workflow_state: str,
) -> int | None:
    if workflow_state not in {"published", "draft", "ready"}:
        raise ValueError("Invalid workflow state")

    if workflow_state == "published":
        conn.execute(
            "UPDATE articles SET workflow_state = 'published', active_batch_id = NULL WHERE article_id = ?",
            (article_id,),
        )
        return None

    batch_id = ensure_open_batch(conn)
    conn.execute(
        "UPDATE articles SET workflow_state = ?, active_batch_id = ? WHERE article_id = ?",
        (workflow_state, batch_id, article_id),
    )
    conn.execute(
        "UPDATE article_batches SET updated_at = ? WHERE batch_id = ?",
        (utc_now(), batch_id),
    )
    return batch_id


def current_batch_info(conn: sqlite3.Connection, *, create: bool = False) -> dict | None:
    if create:
        batch_id = ensure_open_batch(conn)
    else:
        row = conn.execute(
            """
            SELECT batch_id
            FROM article_batches
            WHERE status = 'open'
            ORDER BY batch_id DESC
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None
        batch_id = int(row["batch_id"] if isinstance(row, sqlite3.Row) else row[0])

    batch = conn.execute(
        "SELECT * FROM article_batches WHERE batch_id = ?",
        (batch_id,),
    ).fetchone()
    if batch is None:
        return None

    has_withdrawals = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'article_withdrawals'"
    ).fetchone() is not None
    withdrawal_expr = (
        "EXISTS (SELECT 1 FROM article_withdrawals w "
        "WHERE w.article_id = articles.article_id AND w.status = 'pending')"
        if has_withdrawals
        else "0"
    )

    counts = conn.execute(
        f"""
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN workflow_state = 'draft' THEN 1 ELSE 0 END) AS drafts,
            SUM(CASE WHEN workflow_state = 'ready' THEN 1 ELSE 0 END) AS ready,
            SUM(CASE WHEN edit_state = 'new' THEN 1 ELSE 0 END) AS new_count,
            SUM(CASE WHEN edit_state = 'modified' THEN 1 ELSE 0 END) AS modified_count,
            SUM(CASE WHEN {withdrawal_expr} THEN 1 ELSE 0 END) AS withdrawal_count,
            SUM(CASE WHEN edit_state = 'clean'
                      AND workflow_state IN ('draft', 'ready')
                      AND NOT ({withdrawal_expr})
                     THEN 1 ELSE 0 END) AS image_only_count
        FROM articles
        WHERE active_batch_id = ?
          AND workflow_state IN ('draft', 'ready')
        """,
        (batch_id,),
    ).fetchone()

    def n(name: str) -> int:
        value = counts[name] if isinstance(counts, sqlite3.Row) else 0
        return int(value or 0)

    return {
        "batch_id": batch_id,
        "name": batch["name"],
        "status": batch["status"],
        "created_at": batch["created_at"],
        "updated_at": batch["updated_at"],
        "total": n("total"),
        "drafts": n("drafts"),
        "ready": n("ready"),
        "new": n("new_count"),
        "modified": n("modified_count"),
        "image_only": n("image_only_count"),
        "withdrawals": n("withdrawal_count"),
    }
