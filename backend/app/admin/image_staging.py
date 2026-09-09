from __future__ import annotations

import json
import os
import secrets
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from .article_query import default_repo_root
from .article_store import article_hash, row_to_article, utc_now
from .image_processing import ProcessedImage
from .article_workflow import ensure_open_batch


def image_staging_root() -> Path:
    configured = os.environ.get("WTK_ADMIN_IMAGE_STAGING_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return default_repo_root() / "backend/var/image-staging"


def ensure_image_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS article_image_staging (
            article_id INTEGER PRIMARY KEY REFERENCES articles(article_id) ON DELETE CASCADE,
            generation TEXT NOT NULL,
            staged_at TEXT NOT NULL,
            staged_by TEXT NOT NULL,
            previous_image_filename TEXT NOT NULL DEFAULT '',
            previous_image_path TEXT NOT NULL DEFAULT '',
            source_format TEXT NOT NULL,
            source_bytes INTEGER NOT NULL,
            source_width INTEGER NOT NULL,
            source_height INTEGER NOT NULL,
            full_width INTEGER NOT NULL,
            full_height INTEGER NOT NULL,
            full_bytes INTEGER NOT NULL,
            full_sha256 TEXT NOT NULL,
            thumb_width INTEGER NOT NULL,
            thumb_height INTEGER NOT NULL,
            thumb_bytes INTEGER NOT NULL,
            thumb_sha256 TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS article_image_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL,
            event_type TEXT NOT NULL CHECK(event_type IN ('stage', 'discard')),
            occurred_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            details_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_article_image_events_article
            ON article_image_events(article_id, event_id DESC);
        """
    )


def has_staged_image(conn: sqlite3.Connection, article_id: int) -> bool:
    ensure_image_schema(conn)
    row = conn.execute(
        "SELECT 1 FROM article_image_staging WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    return row is not None


def count_staged_images(conn: sqlite3.Connection) -> int:
    ensure_image_schema(conn)
    return int(conn.execute("SELECT COUNT(*) FROM article_image_staging").fetchone()[0])


def _article_root(article_id: int) -> Path:
    if article_id <= 0:
        raise ValueError("Article ID must be positive")
    return image_staging_root() / str(article_id)


def _generation_dir(article_id: int, generation: str) -> Path:
    # generation is created server-side as secrets.token_hex(); never accept it from a client.
    if not generation or any(ch not in "0123456789abcdef" for ch in generation):
        raise ValueError("Invalid staged image generation")
    return _article_root(article_id) / generation


def _processed_paths(article_id: int, generation: str) -> tuple[Path, Path]:
    base = _generation_dir(article_id, generation)
    return base / f"{article_id}i.jpg", base / f"{article_id}-thumb.jpg"


def _write_processed_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o2770)
    except OSError:
        pass

    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o660)
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _recompute_article_state(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    updated_at: str,
    updated_by: str,
    force_draft: bool,
) -> tuple[str, str]:
    row = conn.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,)).fetchone()
    if row is None:
        raise LookupError("Article not found")

    if row["edit_state"] == "new":
        edit_state = "new"
    else:
        current_hash = article_hash(row_to_article(row))
        edit_state = "clean" if current_hash == row["canonical_hash"] else "modified"

    withdrawal_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'article_withdrawals'"
    ).fetchone()
    pending_withdrawal = False
    if withdrawal_table is not None:
        pending_withdrawal = conn.execute(
            "SELECT 1 FROM article_withdrawals WHERE article_id = ? AND status = 'pending'",
            (article_id,),
        ).fetchone() is not None

    workflow_state = (
        "draft" if force_draft or edit_state != "clean" or pending_withdrawal else "published"
    )
    batch_id = ensure_open_batch(conn) if workflow_state == "draft" else None
    conn.execute(
        """
        UPDATE articles
        SET edit_state = ?, workflow_state = ?, active_batch_id = ?,
            admin_updated_at = ?, admin_updated_by = ?
        WHERE article_id = ?
        """,
        (edit_state, workflow_state, batch_id, updated_at, updated_by, article_id),
    )
    if batch_id is not None:
        conn.execute(
            "UPDATE article_batches SET updated_at = ? WHERE batch_id = ?",
            (updated_at, batch_id),
        )
    return edit_state, workflow_state


def stage_processed_image(
    conn: sqlite3.Connection,
    article_id: int,
    processed: ProcessedImage,
    *,
    staged_by: str,
) -> dict[str, Any]:
    ensure_image_schema(conn)
    article = conn.execute("SELECT * FROM articles WHERE article_id = ?", (article_id,)).fetchone()
    if article is None:
        raise LookupError("Article not found")

    previous_stage = conn.execute(
        "SELECT * FROM article_image_staging WHERE article_id = ?",
        (article_id,),
    ).fetchone()

    if previous_stage is None:
        previous_filename = article["image_filename"]
        previous_path = article["image_path"]
        previous_generation = None
    else:
        previous_filename = previous_stage["previous_image_filename"]
        previous_path = previous_stage["previous_image_path"]
        previous_generation = previous_stage["generation"]

    generation = secrets.token_hex(16)
    full_path, thumb_path = _processed_paths(article_id, generation)

    # Only normalized JPEG bytes reach disk. Raw upload bytes never enter this function.
    try:
        _write_processed_atomic(full_path, processed.full_bytes)
        _write_processed_atomic(thumb_path, processed.thumb_bytes)
    except Exception:
        shutil.rmtree(_generation_dir(article_id, generation), ignore_errors=True)
        raise

    now = utc_now()
    image_filename = f"{article_id}i.jpg"
    image_path = f"/assets/images/article-images/{image_filename}"

    try:
        with conn:
            conn.execute(
                """
                INSERT INTO article_image_staging(
                    article_id, generation, staged_at, staged_by,
                    previous_image_filename, previous_image_path,
                    source_format, source_bytes, source_width, source_height,
                    full_width, full_height, full_bytes, full_sha256,
                    thumb_width, thumb_height, thumb_bytes, thumb_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(article_id) DO UPDATE SET
                    generation = excluded.generation,
                    staged_at = excluded.staged_at,
                    staged_by = excluded.staged_by,
                    source_format = excluded.source_format,
                    source_bytes = excluded.source_bytes,
                    source_width = excluded.source_width,
                    source_height = excluded.source_height,
                    full_width = excluded.full_width,
                    full_height = excluded.full_height,
                    full_bytes = excluded.full_bytes,
                    full_sha256 = excluded.full_sha256,
                    thumb_width = excluded.thumb_width,
                    thumb_height = excluded.thumb_height,
                    thumb_bytes = excluded.thumb_bytes,
                    thumb_sha256 = excluded.thumb_sha256
                """,
                (
                    article_id, generation, now, staged_by,
                    previous_filename, previous_path,
                    processed.source_format, processed.source_bytes,
                    processed.source_width, processed.source_height,
                    processed.full_width, processed.full_height,
                    len(processed.full_bytes), processed.full_sha256,
                    processed.thumb_width, processed.thumb_height,
                    len(processed.thumb_bytes), processed.thumb_sha256,
                ),
            )
            conn.execute(
                """
                UPDATE articles
                SET image_filename = ?, image_path = ?
                WHERE article_id = ?
                """,
                (image_filename, image_path, article_id),
            )
            edit_state, workflow_state = _recompute_article_state(
                conn,
                article_id,
                updated_at=now,
                updated_by=staged_by,
                force_draft=True,
            )
            conn.execute(
                """
                INSERT INTO article_image_events(
                    article_id, event_type, occurred_at, actor, details_json
                ) VALUES (?, 'stage', ?, ?, ?)
                """,
                (
                    article_id,
                    now,
                    staged_by,
                    json.dumps(
                        {
                            "generation": generation,
                            "source_format": processed.source_format,
                            "source_bytes": processed.source_bytes,
                            "source_width": processed.source_width,
                            "source_height": processed.source_height,
                            "full_width": processed.full_width,
                            "full_height": processed.full_height,
                            "full_bytes": len(processed.full_bytes),
                            "full_sha256": processed.full_sha256,
                            "thumb_bytes": len(processed.thumb_bytes),
                            "thumb_sha256": processed.thumb_sha256,
                        },
                        separators=(",", ":"),
                    ),
                ),
            )
    except Exception:
        shutil.rmtree(_generation_dir(article_id, generation), ignore_errors=True)
        raise

    if previous_generation and previous_generation != generation:
        shutil.rmtree(_generation_dir(article_id, previous_generation), ignore_errors=True)

    return {
        "article_id": str(article_id),
        "edit_state": edit_state,
        "workflow_state": workflow_state,
        "staged": staged_image_status(conn, article_id)["staged"],
    }


def staged_image_status(conn: sqlite3.Connection, article_id: int) -> dict[str, Any]:
    ensure_image_schema(conn)
    article = conn.execute(
        "SELECT image_filename, image_path FROM articles WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    if article is None:
        raise LookupError("Article not found")

    stage = conn.execute(
        "SELECT * FROM article_image_staging WHERE article_id = ?",
        (article_id,),
    ).fetchone()

    working = None
    if article["image_filename"]:
        working = {
            "filename": article["image_filename"],
            "path": article["image_path"],
        }

    published_filename = article["image_filename"]
    published_path = article["image_path"]
    if stage is not None:
        published_filename = stage["previous_image_filename"]
        published_path = stage["previous_image_path"]

    published = None
    if published_filename:
        published = {
            "filename": published_filename,
            "path": published_path,
        }

    staged = None
    if stage is not None:
        staged = {
            "staged_at": stage["staged_at"],
            "staged_by": stage["staged_by"],
            "source": {
                "format": stage["source_format"],
                "bytes": stage["source_bytes"],
                "width": stage["source_width"],
                "height": stage["source_height"],
            },
            "full": {
                "width": stage["full_width"],
                "height": stage["full_height"],
                "bytes": stage["full_bytes"],
                "sha256": stage["full_sha256"],
                "preview_url": f"/api/admin/articles/{article_id}/image/full",
            },
            "thumbnail": {
                "width": stage["thumb_width"],
                "height": stage["thumb_height"],
                "bytes": stage["thumb_bytes"],
                "sha256": stage["thumb_sha256"],
                "preview_url": f"/api/admin/articles/{article_id}/image/thumb",
            },
        }

    return {
        "article_id": str(article_id),
        "published": published,
        "working": working,
        "staged": staged,
    }


def staged_image_file(conn: sqlite3.Connection, article_id: int, variant: str) -> Path:
    ensure_image_schema(conn)
    stage = conn.execute(
        "SELECT generation FROM article_image_staging WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    if stage is None:
        raise LookupError("No staged image for this article")

    full_path, thumb_path = _processed_paths(article_id, stage["generation"])
    if variant == "full":
        path = full_path
    elif variant == "thumb":
        path = thumb_path
    else:
        raise ValueError("Invalid staged image variant")

    if not path.is_file():
        raise FileNotFoundError("Staged image file is missing")
    return path


def discard_staged_image(
    conn: sqlite3.Connection,
    article_id: int,
    *,
    discarded_by: str,
) -> dict[str, Any]:
    ensure_image_schema(conn)
    stage = conn.execute(
        "SELECT * FROM article_image_staging WHERE article_id = ?",
        (article_id,),
    ).fetchone()
    if stage is None:
        raise LookupError("No staged image for this article")

    now = utc_now()
    with conn:
        conn.execute(
            """
            UPDATE articles
            SET image_filename = ?, image_path = ?
            WHERE article_id = ?
            """,
            (stage["previous_image_filename"], stage["previous_image_path"], article_id),
        )
        conn.execute("DELETE FROM article_image_staging WHERE article_id = ?", (article_id,))
        edit_state, workflow_state = _recompute_article_state(
            conn,
            article_id,
            updated_at=now,
            updated_by=discarded_by,
            force_draft=False,
        )
        conn.execute(
            """
            INSERT INTO article_image_events(
                article_id, event_type, occurred_at, actor, details_json
            ) VALUES (?, 'discard', ?, ?, ?)
            """,
            (
                article_id,
                now,
                discarded_by,
                json.dumps(
                    {"generation": stage["generation"]},
                    separators=(",", ":"),
                ),
            ),
        )

    shutil.rmtree(_article_root(article_id), ignore_errors=True)
    return {
        "article_id": str(article_id),
        "edit_state": edit_state,
        "workflow_state": workflow_state,
        "staged": None,
    }


def clear_all_staged_images(conn: sqlite3.Connection) -> int:
    """Used only by an explicit discard-drafts refresh."""
    ensure_image_schema(conn)
    count = int(conn.execute("SELECT COUNT(*) FROM article_image_staging").fetchone()[0])
    with conn:
        conn.execute("DELETE FROM article_image_staging")
    shutil.rmtree(image_staging_root(), ignore_errors=True)
    return count
