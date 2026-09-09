from __future__ import annotations

import base64
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from .article_store import row_to_article
from .article_withdrawal import pending_withdrawal_for_article, withdrawal_table_exists

DEFAULT_LIMIT = 100
MAX_LIMIT = 200

SORTS = {
    "posted_desc": {
        "order": "a.posted_date DESC, a.article_id DESC",
        "fields": ("posted_date", "article_id"),
        "direction": "desc",
    },
    "posted_asc": {
        "order": "a.posted_date ASC, a.article_id ASC",
        "fields": ("posted_date", "article_id"),
        "direction": "asc",
    },
    # Retained for API compatibility even though the current UI sorts the
    # visible Publication column by publisher name rather than publication date.
    "publication_desc": {
        "order": "a.publication_date DESC, a.article_id DESC",
        "fields": ("publication_date", "article_id"),
        "direction": "desc",
    },
    "priority_desc": {
        "order": "a.priority DESC, a.article_id DESC",
        "fields": ("priority", "article_id"),
        "direction": "desc",
    },
    "priority_asc": {
        "order": "a.priority ASC, a.article_id ASC",
        "fields": ("priority", "article_id"),
        "direction": "asc",
    },
    "publisher_asc": {
        "order": "a.publication_name COLLATE NOCASE ASC, a.article_id ASC",
        "fields": ("publication_name", "article_id"),
        "direction": "asc",
    },
    "publisher_desc": {
        "order": "a.publication_name COLLATE NOCASE DESC, a.article_id DESC",
        "fields": ("publication_name", "article_id"),
        "direction": "desc",
    },
    "id_desc": {
        "order": "a.article_id DESC",
        "fields": ("article_id",),
        "direction": "desc",
    },
    "id_asc": {
        "order": "a.article_id ASC",
        "fields": ("article_id",),
        "direction": "asc",
    },
    "title_asc": {
        "order": "a.title COLLATE NOCASE ASC, a.article_id ASC",
        "fields": ("title", "article_id"),
        "direction": "asc",
    },
    "title_desc": {
        "order": "a.title COLLATE NOCASE DESC, a.article_id DESC",
        "fields": ("title", "article_id"),
        "direction": "desc",
    },
}


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def admin_db_path() -> Path:
    configured = os.environ.get("WTK_ADMIN_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return default_repo_root() / "backend/var/admin-dev.sqlite3"


def connect_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    path = (db_path or admin_db_path()).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Admin SQLite database not found: {path}")

    # mode=ro makes accidental writes through this connection impossible.
    uri = path.as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _encode_cursor(values: list[Any]) -> str:
    raw = json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> list[Any]:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding)
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid cursor") from exc
    if not isinstance(value, list):
        raise ValueError("Invalid cursor")
    return value


def _cursor_clause(sort: str, cursor: str | None) -> tuple[str, list[Any]]:
    if not cursor:
        return "", []

    spec = SORTS[sort]
    fields = spec["fields"]
    values = _decode_cursor(cursor)
    if len(values) != len(fields):
        raise ValueError("Cursor does not match selected sort")

    direction = spec["direction"]
    op = "<" if direction == "desc" else ">"

    if len(fields) == 1:
        field = fields[0]
        return f"a.{field} {op} ?", [values[0]]

    primary, tie = fields
    if primary in {"title", "publication_name"}:
        clause = (
            f"(a.{primary} COLLATE NOCASE {op} ? OR "
            f"(a.{primary} COLLATE NOCASE = ? AND a.{tie} {op} ?))"
        )
    else:
        clause = (
            f"(a.{primary} {op} ? OR "
            f"(a.{primary} = ? AND a.{tie} {op} ?))"
        )
    return clause, [values[0], values[0], values[1]]


def _cursor_for_row(row: sqlite3.Row, sort: str) -> str:
    values = [row[field] for field in SORTS[sort]["fields"]]
    return _encode_cursor(values)


def list_articles(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    category: str | None = None,
    publisher: str | None = None,
    edit_state: str | None = None,
    workflow_state: str | None = None,
    sort: str = "posted_desc",
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict[str, Any]:
    if sort not in SORTS:
        raise ValueError(f"Unsupported sort: {sort}")
    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    if edit_state not in {None, "clean", "modified", "new"}:
        raise ValueError("Invalid edit_state")
    if workflow_state not in {None, "published", "draft", "ready"}:
        raise ValueError("Invalid workflow_state")

    where: list[str] = []
    params: list[Any] = []

    q = (q or "").strip()
    if q:
        pattern = f"%{_escape_like(q)}%"
        if q.isdigit():
            where.append("(a.article_id = ? OR a.title LIKE ? ESCAPE '\\' COLLATE NOCASE)")
            params.extend([int(q), pattern])
        else:
            where.append("a.title LIKE ? ESCAPE '\\' COLLATE NOCASE")
            params.append(pattern)

    if category:
        where.append(
            "EXISTS (SELECT 1 FROM article_tags t "
            "WHERE t.article_id = a.article_id AND t.tag = ?)"
        )
        params.append(category)

    if publisher:
        where.append("a.publication_group = ?")
        params.append(publisher)

    if edit_state:
        where.append("a.edit_state = ?")
        params.append(edit_state)

    if workflow_state:
        where.append("a.workflow_state = ?")
        params.append(workflow_state)

    # Count is intentionally based only on filters, not the cursor, so the UI can
    # display the total result count while more rows load incrementally.
    filter_sql = " AND ".join(where) if where else "1=1"
    total = conn.execute(
        f"SELECT COUNT(*) FROM articles a WHERE {filter_sql}",
        params,
    ).fetchone()[0]

    page_where = list(where)
    page_params = list(params)
    cursor_sql, cursor_params = _cursor_clause(sort, cursor)
    if cursor_sql:
        page_where.append(cursor_sql)
        page_params.extend(cursor_params)

    page_filter_sql = " AND ".join(page_where) if page_where else "1=1"
    withdrawal_expr = (
        "EXISTS (SELECT 1 FROM article_withdrawals w "
        "WHERE w.article_id = a.article_id AND w.status = 'pending')"
        if withdrawal_table_exists(conn)
        else "0"
    )
    sql = f"""
        SELECT
            a.article_id,
            a.slug,
            a.path,
            a.url,
            a.title,
            a.publication_date,
            a.posted_date,
            a.publication_group,
            a.publication_name,
            a.priority,
            a.summary_markdown,
            a.note_markdown,
            a.tags_json,
            a.image_filename,
            a.image_path,
            a.edit_state,
            a.workflow_state,
            a.active_batch_id,
            {withdrawal_expr} AS withdrawal_pending
        FROM articles a
        WHERE {page_filter_sql}
        ORDER BY {SORTS[sort]['order']}
        LIMIT ?
    """
    rows = conn.execute(sql, [*page_params, limit + 1]).fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        {
            "article_id": str(row["article_id"]),
            "slug": row["slug"],
            "path": row["path"],
            "url": row["url"],
            "title": row["title"],
            "publication_date": row["publication_date"],
            "posted_date": row["posted_date"],
            "publication_group": row["publication_group"],
            "publication_name": row["publication_name"],
            "priority": row["priority"],
            "summary_markdown": row["summary_markdown"],
            "note_markdown": row["note_markdown"],
            "tags": json.loads(row["tags_json"]),
            "image_filename": row["image_filename"],
            "image_path": row["image_path"],
            "edit_state": row["edit_state"],
            "workflow_state": row["workflow_state"],
            "active_batch_id": row["active_batch_id"],
            "withdrawal_pending": bool(row["withdrawal_pending"]),
        }
        for row in rows
    ]

    next_cursor = _cursor_for_row(rows[-1], sort) if has_more and rows else None

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "sort": sort,
        "next_cursor": next_cursor,
    }


def get_article(conn: sqlite3.Connection, article_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM articles WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    if row is None:
        return None

    article = row_to_article(row)
    article["admin"] = {
        "edit_state": row["edit_state"],
        "workflow_state": row["workflow_state"],
        "active_batch_id": row["active_batch_id"],
        "admin_updated_at": row["admin_updated_at"],
        "admin_updated_by": row["admin_updated_by"],
        "withdrawal": pending_withdrawal_for_article(conn, article_id),
    }
    return article
