from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .article_store import article_hash, row_to_article, utc_now
from .article_query import admin_db_path, default_repo_root
from .article_workflow import ensure_open_batch, set_article_workflow
from .image_staging import discard_staged_image, has_staged_image
from .article_withdrawal import pending_withdrawal_for_article

CATEGORY_MAP_PATH = default_repo_root() / "src/site/data/news-category-map.json"
PUBLICATION_MAP_PATH = default_repo_root() / "src/site/data/publication-canonicalization.json"


def connect_writable() -> sqlite3.Connection:
    path = admin_db_path().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Admin SQLite database not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def ensure_edit_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS article_revisions (
            revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL REFERENCES articles(article_id) ON DELETE CASCADE,
            saved_at TEXT NOT NULL,
            saved_by TEXT NOT NULL,
            before_hash TEXT NOT NULL,
            after_hash TEXT NOT NULL,
            before_json TEXT NOT NULL,
            after_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_article_revisions_article
            ON article_revisions(article_id, revision_id DESC);
        """
    )


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Required admin reference file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in admin reference file {path}: {exc}") from exc


def load_category_map() -> dict[str, dict[str, Any]]:
    data = _load_json(CATEGORY_MAP_PATH)
    if not isinstance(data, dict):
        raise ValueError("news-category-map.json must contain an object")
    return data


def load_publication_map() -> dict[str, Any]:
    data = _load_json(PUBLICATION_MAP_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("publications"), dict):
        raise ValueError("publication-canonicalization.json has an unexpected schema")
    return data


def reference_data() -> dict[str, Any]:
    categories = load_category_map()
    publication_data = load_publication_map()

    usage_counts: dict[str, int] = {}
    db_path = admin_db_path().resolve()
    if db_path.is_file():
        uri = db_path.as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as conn:
            usage_counts = {
                str(row[0]): int(row[1])
                for row in conn.execute("SELECT tag, COUNT(*) FROM article_tags GROUP BY tag")
            }

    category_items = [
        {
            "slug": slug,
            "label": str(meta.get("label", slug)),
            "topic": str(meta.get("topic", "")),
            "secondary_topics": list(meta.get("secondary_topics") or []),
            "usage_count": usage_counts.get(slug, 0),
        }
        for slug, meta in categories.items()
    ]
    category_items.sort(key=lambda item: (-item["usage_count"], item["label"].casefold(), item["slug"]))

    publications = [
        {"slug": slug, "display_name": str(meta.get("display_name", slug))}
        for slug, meta in publication_data["publications"].items()
    ]
    publications.sort(key=lambda item: item["display_name"].casefold())

    return {"categories": category_items, "publications": publications}


def _valid_iso_date(value: str, field: str) -> None:
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid YYYY-MM-DD date") from exc


def _valid_http_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _normalized_tags(selected: list[str], existing: list[str], category_map: dict[str, Any]) -> list[str]:
    unknown = sorted(set(selected) - set(category_map))
    if unknown:
        raise ValueError(f"Unknown categories: {', '.join(unknown)}")
    selected_set = set(selected)
    result = [tag for tag in existing if tag in selected_set]
    already = set(result)
    result.extend(tag for tag in selected if tag not in already)
    return result


def slugify_title(title: str) -> str:
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = re.sub(r"-+", "-", slug)
    return slug[:180].strip("-")


def _unique_slug(conn: sqlite3.Connection, title: str, article_id: int) -> str:
    base = slugify_title(title) or f"article-{article_id}"
    candidate = base
    if conn.execute("SELECT 1 FROM articles WHERE slug = ?", (candidate,)).fetchone() is None:
        return candidate
    candidate = f"{base}-{article_id}"
    suffix = 2
    while conn.execute("SELECT 1 FROM articles WHERE slug = ?", (candidate,)).fetchone() is not None:
        candidate = f"{base}-{article_id}-{suffix}"
        suffix += 1
    return candidate


def create_draft_article(
    conn: sqlite3.Connection,
    *,
    title: str,
    source_url: str,
    created_by: str,
) -> dict[str, Any]:
    ensure_edit_schema(conn)
    title = title.strip()
    source_url = source_url.strip()
    if not title:
        raise ValueError("Title is required")
    if not _valid_http_url(source_url):
        raise ValueError("Source URL must begin with http:// or https://")

    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        next_id = int(conn.execute("SELECT COALESCE(MAX(article_id), 0) + 1 FROM articles").fetchone()[0])
        source_order = int(conn.execute("SELECT COALESCE(MAX(source_order), 0) + 1 FROM articles").fetchone()[0])
        slug = _unique_slug(conn, title, next_id)
        batch_id = ensure_open_batch(conn)

        article = {
            "article_id": str(next_id),
            "slug": slug,
            "path": f"/news/{slug}",
            "url": f"https://www.wanttoknow.info/news/{slug}",
            "legacy_url": "",
            "title": title,
            "publication_date": "",
            "posted_date": "",
            "publication_group": "",
            "publication_name": "",
            "publication_detail": "",
            "publication_raw": "",
            "source_url": source_url,
            "summary_markdown": "",
            "note_markdown": "",
            "description_markdown": "",
            "tags": [],
            "related_articles": [],
            "priority": 0,
            "image_filename": "",
            "image_path": "",
            "image_caption_markdown": "",
            "image_caption_text": "",
            "qc_flags": [],
        }

        conn.execute(
            """
            INSERT INTO articles(
                article_id, source_order, slug, path, url, legacy_url, title,
                publication_date, posted_date, publication_group, publication_name,
                publication_detail, publication_raw, source_url, summary_markdown,
                note_markdown, description_markdown, tags_json, related_articles_json,
                priority, image_filename, image_path, image_caption_markdown,
                image_caption_text, qc_flags_json, canonical_hash,
                edit_state, workflow_state, active_batch_id, admin_updated_at, admin_updated_by
            ) VALUES (
                ?, ?, ?, ?, ?, '', ?, '', '', '', '', '', '', ?, '', '', '', '[]', '[]',
                0, '', '', '', '', '[]', '', 'new', 'draft', ?, ?, ?
            )
            """,
            (next_id, source_order, slug, article["path"], article["url"], title, source_url, batch_id, now, created_by),
        )
        conn.execute("UPDATE article_batches SET updated_at = ? WHERE batch_id = ?", (now, batch_id))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {
        "article": article,
        "admin": {
            "edit_state": "new",
            "workflow_state": "draft",
            "active_batch_id": batch_id,
            "admin_updated_at": now,
            "admin_updated_by": created_by,
        },
        "editor_url": f"/admin/articles/{next_id}/edit",
    }


def delete_new_draft_article(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    deleted_by: str,
) -> dict[str, Any]:
    """Delete a never-published draft, retaining a JSON audit snapshot."""
    ensure_edit_schema(conn)
    row = conn.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,)).fetchone()
    if row is None:
        raise LookupError("Article not found")
    if row["edit_state"] != "new" or row["workflow_state"] == "published":
        raise ValueError("Only never-published new drafts can be deleted")

    article = row_to_article(row)
    now = utc_now()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS article_deleted_drafts (
            deletion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            deleted_at TEXT NOT NULL,
            deleted_by TEXT NOT NULL,
            article_json TEXT NOT NULL
        )
        """
    )

    # Remove processed staged files first. This never touches public assets.
    if has_staged_image(conn, article_id):
        discard_staged_image(conn, article_id, discarded_by=deleted_by)

    with conn:
        conn.execute(
            "INSERT INTO article_deleted_drafts(article_id, deleted_at, deleted_by, article_json) VALUES (?, ?, ?, ?)",
            (article_id, now, deleted_by, json.dumps(article, ensure_ascii=False, separators=(",", ":"))),
        )
        conn.execute("DELETE FROM articles WHERE article_id = ?", (article_id,))

    return {
        "deleted": True,
        "article_id": str(article_id),
        "deleted_at": now,
        "deleted_by": deleted_by,
    }


def update_article(
    conn: sqlite3.Connection,
    article_id: int,
    payload: dict[str, Any],
    *,
    saved_by: str,
) -> dict[str, Any]:
    ensure_edit_schema(conn)
    row = conn.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,)).fetchone()
    if row is None:
        raise LookupError("Article not found")

    before = row_to_article(row)
    category_map = load_category_map()
    publication_data = load_publication_map()
    publications = publication_data["publications"]

    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError("Title is required")

    slug = str(payload.get("slug", "")).strip()
    if not slug:
        raise ValueError("Slug is required")
    if "/" in slug or "\\" in slug or "?" in slug or "#" in slug:
        raise ValueError("Slug may not contain /, \\, ? or #")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(ch not in allowed for ch in slug) or not any(ch.isalnum() for ch in slug):
        raise ValueError("Slug may contain only lowercase letters, numbers and hyphens")
    duplicate = conn.execute(
        "SELECT article_id FROM articles WHERE slug = ? AND article_id <> ?",
        (slug, article_id),
    ).fetchone()
    if duplicate is not None:
        raise ValueError(f"Slug is already used by article {duplicate['article_id']}")

    publication_group = str(payload.get("publication_group", "")).strip()
    if publication_group:
        if publication_group not in publications:
            raise ValueError("Choose a canonical publication from the publication list")
        publication_name = str(publications[publication_group].get("display_name", publication_group))
    else:
        publication_name = ""

    publication_date = str(payload.get("publication_date", "")).strip()
    posted_date = str(payload.get("posted_date", "")).strip()
    if publication_date:
        _valid_iso_date(publication_date, "Publication date")
    if posted_date:
        _valid_iso_date(posted_date, "WTK posted date")

    priority = payload.get("priority", 0)
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError("Priority must be an integer")
    if not 0 <= priority <= 1000:
        raise ValueError("Priority must be between 0 and 1000")

    source_url = str(payload.get("source_url", "")).strip()
    warnings: list[str] = []
    is_new = row["edit_state"] == "new" or not row["canonical_hash"]
    if is_new:
        if not _valid_http_url(source_url):
            raise ValueError("Source URL is required and must begin with http:// or https://")
    elif source_url != before["source_url"] and source_url and not _valid_http_url(source_url):
        raise ValueError("A changed source URL must begin with http:// or https://")
    elif source_url and not _valid_http_url(source_url):
        warnings.append("This article retains a legacy malformed source URL. It was not changed by this save.")

    selected_tags = payload.get("tags", [])
    if not isinstance(selected_tags, list) or not all(isinstance(tag, str) for tag in selected_tags):
        raise ValueError("Categories must be a list of category slugs")
    tags = _normalized_tags(selected_tags, before["tags"], category_map)

    after = {
        "article_id": before["article_id"],
        "slug": slug,
        "path": f"/news/{slug}",
        "url": f"https://www.wanttoknow.info/news/{slug}",
        "legacy_url": str(payload.get("legacy_url", "")).strip(),
        "title": title,
        "publication_date": publication_date,
        "posted_date": posted_date,
        "publication_group": publication_group,
        "publication_name": publication_name,
        "publication_detail": str(payload.get("publication_detail", "")),
        "publication_raw": str(payload.get("publication_raw", "")),
        "source_url": source_url,
        "summary_markdown": str(payload.get("summary_markdown", "")),
        "note_markdown": str(payload.get("note_markdown", "")),
        "description_markdown": before["description_markdown"],
        "tags": tags,
        "related_articles": before["related_articles"],
        "priority": priority,
        "image_filename": before["image_filename"],
        "image_path": before["image_path"],
        "image_caption_markdown": str(payload.get("image_caption_markdown", "")),
        "image_caption_text": str(payload.get("image_caption_text", "")),
        "qc_flags": before["qc_flags"],
    }

    before_hash = article_hash(before)
    after_hash = article_hash(after)
    canonical_hash = row["canonical_hash"]
    if is_new:
        edit_state = "new"
    else:
        edit_state = "clean" if after_hash == canonical_hash else "modified"
    pending_withdrawal = pending_withdrawal_for_article(conn, article_id)
    workflow_state = (
        "draft"
        if edit_state != "clean" or has_staged_image(conn, article_id) or pending_withdrawal is not None
        else "published"
    )
    now = utc_now()

    with conn:
        if workflow_state == "draft":
            batch_id = ensure_open_batch(conn)
        else:
            batch_id = None
        conn.execute(
            """
            UPDATE articles SET
                slug = ?, path = ?, url = ?, legacy_url = ?, title = ?,
                publication_date = ?, posted_date = ?, publication_group = ?,
                publication_name = ?, publication_detail = ?, publication_raw = ?,
                source_url = ?, summary_markdown = ?, note_markdown = ?,
                description_markdown = ?, tags_json = ?, priority = ?,
                image_caption_markdown = ?, image_caption_text = ?,
                edit_state = ?, workflow_state = ?, active_batch_id = ?, admin_updated_at = ?,
                admin_updated_by = ?
            WHERE article_id = ?
            """,
            (
                after["slug"], after["path"], after["url"], after["legacy_url"], after["title"],
                after["publication_date"], after["posted_date"], after["publication_group"],
                after["publication_name"], after["publication_detail"], after["publication_raw"],
                after["source_url"], after["summary_markdown"], after["note_markdown"],
                after["description_markdown"], json.dumps(after["tags"], ensure_ascii=False, separators=(",", ":")),
                after["priority"], after["image_caption_markdown"], after["image_caption_text"],
                edit_state, workflow_state, batch_id, now, saved_by, article_id,
            ),
        )
        conn.execute("DELETE FROM article_tags WHERE article_id = ?", (article_id,))
        conn.executemany(
            "INSERT INTO article_tags(article_id, tag) VALUES (?, ?)",
            ((article_id, tag) for tag in after["tags"]),
        )
        conn.execute(
            """
            INSERT INTO article_revisions(
                article_id, saved_at, saved_by, before_hash, after_hash, before_json, after_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article_id, now, saved_by, before_hash, after_hash,
                json.dumps(before, ensure_ascii=False, separators=(",", ":")),
                json.dumps(after, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        if batch_id is not None:
            conn.execute("UPDATE article_batches SET updated_at = ? WHERE batch_id = ?", (now, batch_id))

    return {
        "article": after,
        "admin": {
            "edit_state": edit_state,
            "workflow_state": workflow_state,
            "active_batch_id": batch_id,
            "admin_updated_at": now,
            "admin_updated_by": saved_by,
            "withdrawal": pending_withdrawal,
        },
        "warnings": warnings,
    }
