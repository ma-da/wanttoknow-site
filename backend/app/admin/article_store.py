from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

CANONICAL_FIELDS = (
    "article_id",
    "slug",
    "path",
    "url",
    "legacy_url",
    "title",
    "publication_date",
    "posted_date",
    "publication_group",
    "publication_name",
    "publication_detail",
    "publication_raw",
    "source_url",
    "summary_markdown",
    "note_markdown",
    "description_markdown",
    "tags",
    "related_articles",
    "priority",
    "image_filename",
    "image_path",
    "image_caption_markdown",
    "image_caption_text",
    "qc_flags",
)

TEXT_FIELDS = (
    "slug",
    "path",
    "url",
    "legacy_url",
    "title",
    "publication_date",
    "posted_date",
    "publication_group",
    "publication_name",
    "publication_detail",
    "publication_raw",
    "source_url",
    "summary_markdown",
    "note_markdown",
    "description_markdown",
    "image_filename",
    "image_path",
    "image_caption_markdown",
    "image_caption_text",
)

LIST_FIELDS = ("tags", "related_articles", "qc_flags")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE admin_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE article_batches (
            batch_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'published', 'abandoned')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            published_at TEXT
        );

        CREATE TABLE articles (
            article_id INTEGER PRIMARY KEY,
            source_order INTEGER NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            path TEXT NOT NULL,
            url TEXT NOT NULL,
            legacy_url TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            publication_date TEXT NOT NULL,
            posted_date TEXT NOT NULL,
            publication_group TEXT NOT NULL,
            publication_name TEXT NOT NULL,
            publication_detail TEXT NOT NULL DEFAULT '',
            publication_raw TEXT NOT NULL DEFAULT '',
            source_url TEXT NOT NULL DEFAULT '',
            summary_markdown TEXT NOT NULL DEFAULT '',
            note_markdown TEXT NOT NULL DEFAULT '',
            description_markdown TEXT NOT NULL DEFAULT '',
            tags_json TEXT NOT NULL DEFAULT '[]',
            related_articles_json TEXT NOT NULL DEFAULT '[]',
            priority INTEGER NOT NULL,
            image_filename TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            image_caption_markdown TEXT NOT NULL DEFAULT '',
            image_caption_text TEXT NOT NULL DEFAULT '',
            qc_flags_json TEXT NOT NULL DEFAULT '[]',

            canonical_hash TEXT NOT NULL,
            edit_state TEXT NOT NULL DEFAULT 'clean'
                CHECK (edit_state IN ('clean', 'modified', 'new')),
            workflow_state TEXT NOT NULL DEFAULT 'published'
                CHECK (workflow_state IN ('published', 'draft', 'ready')),
            active_batch_id INTEGER REFERENCES article_batches(batch_id),
            admin_updated_at TEXT,
            admin_updated_by TEXT
        );

        CREATE TABLE article_tags (
            article_id INTEGER NOT NULL REFERENCES articles(article_id) ON DELETE CASCADE,
            tag TEXT NOT NULL,
            PRIMARY KEY (article_id, tag)
        );

        CREATE INDEX idx_articles_title_nocase
            ON articles(title COLLATE NOCASE);
        CREATE INDEX idx_articles_publication_group
            ON articles(publication_group);
        CREATE INDEX idx_articles_publication_date
            ON articles(publication_date DESC);
        CREATE INDEX idx_articles_posted_date
            ON articles(posted_date DESC);
        CREATE INDEX idx_articles_priority
            ON articles(priority DESC);
        CREATE INDEX idx_articles_edit_state
            ON articles(edit_state);
        CREATE INDEX idx_articles_batch
            ON articles(active_batch_id);
        CREATE INDEX idx_article_tags_tag
            ON article_tags(tag, article_id);

        CREATE VIRTUAL TABLE article_fts USING fts5(
            title,
            publication_name,
            publication_group,
            summary_markdown,
            content='articles',
            content_rowid='article_id'
        );

        CREATE TRIGGER articles_ai AFTER INSERT ON articles BEGIN
            INSERT INTO article_fts(
                rowid, title, publication_name, publication_group, summary_markdown
            ) VALUES (
                new.article_id, new.title, new.publication_name,
                new.publication_group, new.summary_markdown
            );
        END;

        CREATE TRIGGER articles_ad AFTER DELETE ON articles BEGIN
            INSERT INTO article_fts(
                article_fts, rowid, title, publication_name,
                publication_group, summary_markdown
            ) VALUES (
                'delete', old.article_id, old.title, old.publication_name,
                old.publication_group, old.summary_markdown
            );
        END;

        CREATE TRIGGER articles_au AFTER UPDATE OF
            title, publication_name, publication_group, summary_markdown
        ON articles BEGIN
            INSERT INTO article_fts(
                article_fts, rowid, title, publication_name,
                publication_group, summary_markdown
            ) VALUES (
                'delete', old.article_id, old.title, old.publication_name,
                old.publication_group, old.summary_markdown
            );
            INSERT INTO article_fts(
                rowid, title, publication_name, publication_group, summary_markdown
            ) VALUES (
                new.article_id, new.title, new.publication_name,
                new.publication_group, new.summary_markdown
            );
        END;
        """
    )
    set_state(conn, "schema_version", "1")


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO admin_state(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def canonical_json(article: dict[str, Any]) -> str:
    return json.dumps(
        article,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def article_hash(article: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(article).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_article(article: dict[str, Any], line_no: int | None = None) -> None:
    where = f" on line {line_no}" if line_no is not None else ""
    actual = tuple(article.keys())
    if set(actual) != set(CANONICAL_FIELDS):
        missing = sorted(set(CANONICAL_FIELDS) - set(actual))
        extra = sorted(set(actual) - set(CANONICAL_FIELDS))
        raise ValueError(f"Canonical field mismatch{where}; missing={missing}, extra={extra}")

    article_id = article["article_id"]
    if not isinstance(article_id, str) or not article_id.isdigit():
        raise ValueError(f"article_id must be a numeric string{where}: {article_id!r}")
    if len(article_id) > 1 and article_id.startswith("0"):
        raise ValueError(f"article_id may not contain leading zeroes{where}: {article_id!r}")

    for field in TEXT_FIELDS:
        if not isinstance(article[field], str):
            raise ValueError(f"{field} must be a string{where}")

    priority = article["priority"]
    if isinstance(priority, bool) or not isinstance(priority, int):
        raise ValueError(f"priority must be an integer{where}")

    for field in LIST_FIELDS:
        value = article[field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{field} must be a list of strings{where}")


def iter_jsonl(path: Path) -> Iterator[tuple[int, dict[str, Any]]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                article = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_no}: {exc}") from exc
            validate_article(article, line_no)
            yield line_no, article


def import_master(conn: sqlite3.Connection, master_path: Path) -> int:
    insert_sql = """
        INSERT INTO articles (
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
    """

    count = 0
    imported_at = utc_now()
    with conn:
        for source_order, (_, a) in enumerate(iter_jsonl(master_path), 1):
            conn.execute(
                insert_sql,
                (
                    int(a["article_id"]),
                    source_order,
                    a["slug"],
                    a["path"],
                    a["url"],
                    a["legacy_url"],
                    a["title"],
                    a["publication_date"],
                    a["posted_date"],
                    a["publication_group"],
                    a["publication_name"],
                    a["publication_detail"],
                    a["publication_raw"],
                    a["source_url"],
                    a["summary_markdown"],
                    a["note_markdown"],
                    a["description_markdown"],
                    compact_json(a["tags"]),
                    compact_json(a["related_articles"]),
                    a["priority"],
                    a["image_filename"],
                    a["image_path"],
                    a["image_caption_markdown"],
                    a["image_caption_text"],
                    compact_json(a["qc_flags"]),
                    article_hash(a),
                ),
            )
            conn.executemany(
                "INSERT INTO article_tags(article_id, tag) VALUES (?, ?)",
                ((int(a["article_id"]), tag) for tag in a["tags"]),
            )
            count += 1

        set_state(conn, "master_sha256", file_sha256(master_path))
        set_state(conn, "master_record_count", str(count))
        set_state(conn, "master_imported_at", imported_at)

    return count


def row_to_article(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "article_id": str(row["article_id"]),
        "slug": row["slug"],
        "path": row["path"],
        "url": row["url"],
        "legacy_url": row["legacy_url"],
        "title": row["title"],
        "publication_date": row["publication_date"],
        "posted_date": row["posted_date"],
        "publication_group": row["publication_group"],
        "publication_name": row["publication_name"],
        "publication_detail": row["publication_detail"],
        "publication_raw": row["publication_raw"],
        "source_url": row["source_url"],
        "summary_markdown": row["summary_markdown"],
        "note_markdown": row["note_markdown"],
        "description_markdown": row["description_markdown"],
        "tags": json.loads(row["tags_json"]),
        "related_articles": json.loads(row["related_articles_json"]),
        "priority": row["priority"],
        "image_filename": row["image_filename"],
        "image_path": row["image_path"],
        "image_caption_markdown": row["image_caption_markdown"],
        "image_caption_text": row["image_caption_text"],
        "qc_flags": json.loads(row["qc_flags_json"]),
    }


def export_master(conn: sqlite3.Connection, output_path: Path) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(output_path.name + ".tmp")
    count = 0

    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as f:
            for row in conn.execute("SELECT * FROM articles ORDER BY source_order"):
                article = row_to_article(row)
                validate_article(article)
                f.write(compact_json(article) + "\n")
                count += 1
        temp_path.replace(output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return count


def semantic_sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    count = 0
    for _, article in iter_jsonl(path):
        h.update(canonical_json(article).encode("utf-8"))
        h.update(b"\n")
        count += 1
    return h.hexdigest(), count


def verify_roundtrip(original_path: Path, exported_path: Path) -> tuple[int, str]:
    original_hash, original_count = semantic_sha256(original_path)
    exported_hash, exported_count = semantic_sha256(exported_path)

    if original_count != exported_count:
        raise ValueError(
            f"Record count mismatch: original={original_count}, exported={exported_count}"
        )
    if original_hash != exported_hash:
        raise ValueError(
            "Semantic content mismatch between original and exported JSONL: "
            f"original={original_hash}, exported={exported_hash}"
        )
    return original_count, original_hash
