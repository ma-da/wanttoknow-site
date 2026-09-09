#!/usr/bin/env python3
"""
Build the WantToKnow.info phase-1 SQLite + FTS5 search database.

The database is a DERIVED artifact. JSONL/CSV source corpora remain authoritative.

Default inputs
--------------
src/site/data/article-index.jsonl
src/site/data/corpus/document-chunks-v1.jsonl
src/site/data/corpus/youtube-search-chunks-v1.jsonl
src/site/data/corpus/ref-registry-v1.jsonl

News full-text source
---------------------
Defaults explicitly to:
src/site/data/wtk_articles_master.jsonl

Use --news-source only for deliberate testing/overrides. The builder does not
auto-discover alternate masters, so backup/intermediate files can never be
selected accidentally.

Output
------
src/site/data/search/wanttoknow-search.sqlite
reports/build/search-db-build.json

Core model
----------
ref_registry
    Persistent universal identifiers, including future inactive/tombstoned refs.

content
    One row per ACTIVE searchable ref_id, normalized across news, page chunks,
    Substack chunks, and YouTube transcript chunks. `text` is normalized for
    search; `display_markdown` preserves presentation Markdown separately.

content_terms
    Normalized topic/tag/playlist/section terms for filtering.

fts_content
    FTS5 external-content index over title, text, publisher, and topics.

related_content
    Empty phase-1 table reserved for the later TF-IDF top-24 neighbor index:
    (ref_id, related_ref_id, rank). No score is required unless desired later.

Typical use
-----------
cd /mnt/c/datasources/wanttoknow-site
python scripts/build-search-db.py
"""

from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable
import csv
import hashlib
import json
import os
import re
import sqlite3
import sys


DEFAULT_SITE_ROOT = Path("/mnt/c/datasources/wanttoknow-site")
SITE_ORIGIN = "https://www.wanttoknow.info"

NEWS_REF_MIN = 1
NEWS_REF_MAX = 99_999
DOCUMENT_REF_MIN = 100_000
DOCUMENT_REF_MAX = 999_999
YOUTUBE_REF_MIN = 1_000_000

WORD_RE = re.compile(r"\S+")
WS_RE = re.compile(r"\s+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MD_REF_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*", re.M)
MD_LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+", re.M)
MD_QUOTE_RE = re.compile(r"^\s*>\s?", re.M)


# ============================================================================
# Generic helpers
# ============================================================================

def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def clean(value: Any) -> str:
    return WS_RE.sub(
        " ",
        ""
        if value is None
        else str(value),
    ).strip()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def parse_jsonish_list(value: Any) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        return stable_unique_strings(value)

    if isinstance(value, tuple):
        return stable_unique_strings(value)

    text = clean(value)

    if not text:
        return []

    try:
        parsed = json.loads(text)

        if isinstance(parsed, list):
            return stable_unique_strings(parsed)
    except (json.JSONDecodeError, TypeError):
        pass

    # Conservative fallback for old CSV-style list strings.
    if "," in text:
        return stable_unique_strings(
            part.strip()
            for part in text.split(",")
        )

    return [text]


def stable_unique_strings(
    values: Iterable[Any],
) -> list[str]:
    output = []
    seen = set()

    for value in values:
        text = clean(value)

        if not text:
            continue

        marker = text.casefold()

        if marker in seen:
            continue

        seen.add(marker)
        output.append(text)

    return output


def markdown_to_text(value: Any) -> str:
    """
    Lightweight plain-text conversion for news-summary Markdown/legacy markup.

    Page/Substack/YouTube chunk sources are already plain text; this is primarily
    for the news master.
    """
    text = unescape(
        ""
        if value is None
        else str(value)
    )

    text = MD_IMAGE_RE.sub(
        lambda match: match.group(1),
        text,
    )

    text = MD_LINK_RE.sub(
        lambda match: match.group(1),
        text,
    )

    text = MD_REF_LINK_RE.sub(
        lambda match: match.group(1),
        text,
    )

    text = MD_HEADING_RE.sub(
        "",
        text,
    )

    text = MD_LIST_RE.sub(
        "",
        text,
    )

    text = MD_QUOTE_RE.sub(
        "",
        text,
    )

    text = re.sub(
        r"`([^`]+)`",
        r"\1",
        text,
    )

    text = HTML_TAG_RE.sub(
        " ",
        text,
    )

    for marker in (
        "**",
        "__",
        "~~",
        "*",
        "_",
    ):
        text = text.replace(
            marker,
            "",
        )

    return clean(text)


def canonical_site_url(
    value: Any,
    slug: Any = None,
) -> str:
    url = clean(value)

    if url:
        if url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            return url

        if not url.startswith("/"):
            url = "/" + url

        return url

    slug_text = clean(slug)

    if slug_text:
        return (
            "/news/"
            + slug_text.strip("/")
        )

    return ""


def pick(
    mapping: dict[str, Any],
    *names: str,
) -> Any:
    lowered = {
        str(key).casefold():
            value
        for key, value in mapping.items()
    }

    for name in names:
        value = lowered.get(
            name.casefold()
        )

        if value is not None:
            if isinstance(value, (list, dict)):
                return value

            if clean(value):
                return value

    return None


def parse_priority(value: Any) -> float | None:
    if value is None:
        return None

    text = clean(value)

    if not text:
        return None

    try:
        return float(text)
    except (TypeError, ValueError):
        return None


# ============================================================================
# JSONL / CSV loading
# ============================================================================

def load_jsonl(
    path: Path,
) -> list[dict[str, Any]]:
    rows = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        for line_no, line in enumerate(
            f,
            1,
        ):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path}:{line_no}: invalid JSON: {exc}"
                ) from exc

            if not isinstance(
                row,
                dict,
            ):
                raise RuntimeError(
                    f"{path}:{line_no}: expected JSON object."
                )

            rows.append(row)

    return rows


def load_table(
    path: Path,
) -> list[dict[str, Any]]:
    suffix = path.suffix.casefold()

    if suffix == ".jsonl":
        return load_jsonl(path)

    if suffix == ".json":
        value = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(value, list):
            raise RuntimeError(
                f"{path}: expected a JSON array."
            )

        if not all(
            isinstance(row, dict)
            for row in value
        ):
            raise RuntimeError(
                f"{path}: expected array of JSON objects."
            )

        return value

    if suffix == ".csv":
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            return list(
                csv.DictReader(f)
            )

    raise RuntimeError(
        "Unsupported news master format: "
        f"{path.suffix}"
    )


# ============================================================================
# News source normalization
# ============================================================================

def news_id(
    row: dict[str, Any],
) -> int:
    value = pick(
        row,
        "id",
        "article_id",
        "ArticleId",
    )

    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid news ArticleID: {value!r}"
        ) from exc

    if not (
        NEWS_REF_MIN
        <= result
        <= NEWS_REF_MAX
    ):
        raise RuntimeError(
            f"News ArticleID {result} is outside 1..99,999."
        )

    return result


def news_search_text(
    row: dict[str, Any],
) -> str:
    summary = pick(
        row,
        "summary_markdown",
        "summary",
        "Summary",
    )

    note = pick(
        row,
        "note_markdown",
        "note",
        "Note",
    )

    if summary:
        pieces = [
            markdown_to_text(summary),
        ]

        if note:
            pieces.append(
                markdown_to_text(note)
            )

        return clean(
            " ".join(
                piece
                for piece in pieces
                if piece
            )
        )

    fallback = pick(
        row,
        "description_markdown",
        "description",
        "Description",
        "content_text",
        "text",
    )

    return markdown_to_text(
        fallback
    )


def news_display_markdown(
    row: dict[str, Any],
) -> str:
    """
    Preserve the authoritative news presentation Markdown for expanded results.

    Searchable plain text is built separately by news_search_text(). This field
    is deliberately not normalized with clean(), because Markdown depends on
    line breaks and punctuation.
    """
    summary = pick(
        row,
        "summary_markdown",
        "summary",
        "Summary",
    )

    note = pick(
        row,
        "note_markdown",
        "note",
        "Note",
    )

    parts = []

    if summary:
        parts.append(
            str(summary).strip()
        )

    if note:
        parts.append(
            "### Note\n\n"
            + str(note).strip()
        )

    if parts:
        return "\n\n".join(parts)

    fallback = pick(
        row,
        "description_markdown",
        "description",
        "Description",
    )

    return str(fallback or "").strip()


# ============================================================================
# Universal content normalization
# ============================================================================

def make_content_row(
    *,
    ref_id: int,
    family: str,
    record_type: str,
    source_key: str,
    source_id: str,
    chunk_index: int | None,
    title: str,
    url: str,
    published_at: str | None,
    publisher: str | None,
    section: str | None,
    topic: str | None,
    terms: list[tuple[str, str]],
    text: str,
    display_markdown: str,
    priority: float | None,
    metadata: dict[str, Any],
) -> tuple[
    dict[str, Any],
    list[tuple[int, str, str]],
]:
    normalized_terms = []
    seen = set()

    for kind, value in terms:
        kind_text = clean(kind).casefold()
        value_text = clean(value)

        if not kind_text or not value_text:
            continue

        marker = (
            kind_text,
            value_text.casefold(),
        )

        if marker in seen:
            continue

        seen.add(marker)

        normalized_terms.append(
            (
                ref_id,
                kind_text,
                value_text,
            )
        )

    searchable_terms = stable_unique_strings(
        value
        for _, _, value in normalized_terms
    )

    return (
        {
            "ref_id":
                ref_id,
            "family":
                family,
            "record_type":
                record_type,
            "source_key":
                source_key,
            "source_id":
                source_id,
            "chunk_index":
                chunk_index,
            "title":
                clean(title),
            "url":
                clean(url),
            "published_at":
                clean(published_at)
                or None,
            "publisher":
                clean(publisher)
                or None,
            "section":
                clean(section)
                or None,
            "topic":
                clean(topic)
                or None,
            "topics":
                " ".join(
                    searchable_terms
                ),
            # Normalized plain text used by FTS5 and snippets.
            "text":
                clean(text),

            # Presentation/source Markdown. Never collapse its whitespace.
            "display_markdown":
                str(display_markdown or "").strip(),

            "priority":
                priority,
            "metadata_json":
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
        },
        normalized_terms,
    )


def build_news_content(
    registry_rows: list[dict[str, Any]],
    article_index_rows: list[dict[str, Any]],
    news_master_rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, str, str]],
]:
    index_by_id = {}

    for row in article_index_rows:
        aid = news_id(row)

        if aid in index_by_id:
            raise RuntimeError(
                f"Duplicate ArticleID in article-index.jsonl: {aid}"
            )

        index_by_id[aid] = row

    master_by_id = {}

    for row in news_master_rows:
        try:
            aid = news_id(row)
        except RuntimeError:
            continue

        if aid in master_by_id:
            raise RuntimeError(
                f"Duplicate ArticleID in full news master: {aid}"
            )

        master_by_id[aid] = row

    active_news_refs = sorted(
        (
            row
            for row in registry_rows
            if row.get("active")
            and row.get("family") == "news"
        ),
        key=lambda row: row["ref_id"],
    )

    content_rows = []
    term_rows = []

    missing_index = []
    missing_master = []
    empty_text = []

    for reg in active_news_refs:
        ref_id = int(
            reg["ref_id"]
        )

        index_row = index_by_id.get(
            ref_id
        )

        master_row = master_by_id.get(
            ref_id
        )

        if index_row is None:
            missing_index.append(
                ref_id
            )
            continue

        if master_row is None:
            missing_master.append(
                ref_id
            )
            continue

        text = news_search_text(
            master_row
        )

        if not text:
            empty_text.append(
                ref_id
            )
            continue

        slug = pick(
            index_row,
            "slug",
        ) or pick(
            master_row,
            "slug",
        )

        url = canonical_site_url(
            (
                pick(
                    index_row,
                    "url",
                    "path",
                )
                or pick(
                    master_row,
                    "wtkURL",
                    "url",
                    "path",
                )
            ),
            slug=slug,
        )

        title = (
            pick(
                index_row,
                "title",
            )
            or pick(
                master_row,
                "title",
                "Title",
            )
            or ""
        )

        published_at = (
            pick(
                index_row,
                "date",
                "publication_date",
                "published_at",
            )
            or pick(
                master_row,
                "publication_date",
                "PublicationDate",
                "published_at",
                "date",
            )
        )

        publisher = (
            pick(
                index_row,
                "publisher",
                "publication",
            )
            or pick(
                master_row,
                "publication_name",
                "publisher",
                "Publication",
            )
        )

        tags = stable_unique_strings(
            parse_jsonish_list(
                pick(
                    index_row,
                    "tags",
                )
            )
            + parse_jsonish_list(
                pick(
                    master_row,
                    "tags",
                )
            )
        )

        terms = [
            (
                "tag",
                tag,
            )
            for tag in tags
        ]

        priority = parse_priority(
            (
                pick(
                    index_row,
                    "priority",
                )
                or pick(
                    master_row,
                    "priority",
                    "Priority",
                )
            )
        )

        content, terms_out = make_content_row(
            ref_id=ref_id,
            family="news",
            record_type="news",
            source_key=reg["source_key"],
            source_id=reg["source_id"],
            chunk_index=None,
            title=title,
            url=url,
            published_at=published_at,
            publisher=publisher,
            section="news",
            topic=None,
            terms=terms,
            text=text,
            display_markdown=news_display_markdown(
                master_row
            ),
            priority=priority,
            metadata={
                "article_id":
                    ref_id,
                "slug":
                    clean(slug)
                    or None,
                "tags":
                    tags,
                "source_url":
                    clean(
                        pick(
                            master_row,
                            "source_url",
                            "sourceUrl",
                            "SourceURL",
                        )
                    )
                    or None,
            },
        )

        content_rows.append(
            content
        )

        term_rows.extend(
            terms_out
        )

    if missing_index:
        raise RuntimeError(
            "Active news refs missing from article-index.jsonl: "
            f"{len(missing_index)}; examples={missing_index[:20]}"
        )

    if missing_master:
        raise RuntimeError(
            "Active news refs missing from full news master: "
            f"{len(missing_master)}; examples={missing_master[:20]}"
        )

    if empty_text:
        raise RuntimeError(
            "Active news records have no searchable summary text: "
            f"{len(empty_text)}; examples={empty_text[:20]}"
        )

    return (
        content_rows,
        term_rows,
    )


def build_document_content(
    document_rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, str, str]],
]:
    content_rows = []
    term_rows = []

    for row in document_rows:
        ref_id = int(
            row["ref_id"]
        )

        terms = []

        for value in row.get(
            "topics"
        ) or []:
            terms.append(
                (
                    "topic",
                    value,
                )
            )

        for value in row.get(
            "tags"
        ) or []:
            terms.append(
                (
                    "tag",
                    value,
                )
            )

        if row.get(
            "section"
        ):
            terms.append(
                (
                    "section",
                    row[
                        "section"
                    ],
                )
            )

        if row.get(
            "topic"
        ):
            terms.append(
                (
                    "topic",
                    row[
                        "topic"
                    ],
                )
            )

        content, terms_out = make_content_row(
            ref_id=ref_id,
            family="document",
            record_type=row["record_type"],
            source_key=row["source_key"],
            source_id=row["source_id"],
            chunk_index=row["chunk_index"],
            title=row.get("title") or "",
            url=row.get("url") or "",
            published_at=row.get("published_at"),
            publisher=(
                "PEERS Substack"
                if row["record_type"] == "substack_chunk"
                else "WTK Page"
            ),
            section=row.get("section"),
            topic=row.get("topic"),
            terms=terms,
            text=row.get("text") or "",
            display_markdown="",
            priority=parse_priority(
                row.get(
                    "priority"
                )
            ),
            metadata={
                "heading":
                    row.get(
                        "heading"
                    ),
                "headings":
                    row.get(
                        "headings"
                    )
                    or [],
                "heading_paths":
                    row.get(
                        "heading_paths"
                    )
                    or [],
                "source_word_start":
                    row.get(
                        "source_word_start"
                    ),
                "source_word_end":
                    row.get(
                        "source_word_end"
                    ),
                "source_word_count":
                    row.get(
                        "source_word_count"
                    ),
                "qc_flags":
                    row.get(
                        "qc_flags"
                    )
                    or [],
            },
        )

        content_rows.append(
            content
        )

        term_rows.extend(
            terms_out
        )

    return (
        content_rows,
        term_rows,
    )


def build_youtube_content(
    youtube_rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[tuple[int, str, str]],
]:
    content_rows = []
    term_rows = []

    for row in youtube_rows:
        ref_id = int(
            row["ref_id"]
        )

        terms = []

        for value in row.get(
            "topics"
        ) or []:
            terms.append(
                (
                    "topic",
                    value,
                )
            )

        for value in row.get(
            "playlists"
        ) or []:
            terms.append(
                (
                    "playlist",
                    value,
                )
            )

        content, terms_out = make_content_row(
            ref_id=ref_id,
            family="youtube",
            record_type="youtube_chunk",
            source_key=row["source_key"],
            source_id=row["video_id"],
            chunk_index=row["chunk_index"],
            title=row.get(
                "video_title"
            ) or "",
            url=row.get(
                "timestamp_url"
            ) or row.get(
                "video_url"
            ) or "",
            published_at=row.get(
                "published_at"
            ),
            publisher="PEERS Conscious Media",
            section="videos",
            topic=None,
            terms=terms,
            text=row.get(
                "text"
            ) or "",
            display_markdown="",
            priority=parse_priority(
                row.get(
                    "priority"
                )
            ),
            metadata={
                "video_id":
                    row.get(
                        "video_id"
                    ),
                "video_url":
                    row.get(
                        "video_url"
                    ),
                "timestamp_seconds":
                    row.get(
                        "timestamp_seconds"
                    ),
                "timestamp_formatted":
                    row.get(
                        "timestamp_formatted"
                    ),
                "end_seconds":
                    row.get(
                        "end_seconds"
                    ),
                "caption_type":
                    row.get(
                        "caption_type"
                    ),
                "caption_language":
                    row.get(
                        "caption_language"
                    ),
                "playlists":
                    row.get(
                        "playlists"
                    )
                    or [],
                "qc_flags":
                    row.get(
                        "qc_flags"
                    )
                    or [],
            },
        )

        content_rows.append(
            content
        )

        term_rows.extend(
            terms_out
        )

    return (
        content_rows,
        term_rows,
    )


# ============================================================================
# SQLite creation
# ============================================================================

SCHEMA_SQL = r"""
PRAGMA foreign_keys = ON;

CREATE TABLE build_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
) WITHOUT ROWID;

CREATE TABLE ref_registry (
    ref_id INTEGER PRIMARY KEY,
    family TEXT NOT NULL
        CHECK (family IN ('news', 'document', 'youtube')),
    record_type TEXT NOT NULL
        CHECK (
            record_type IN (
                'news',
                'page_chunk',
                'substack_chunk',
                'youtube_chunk'
            )
        ),
    source_key TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    chunk_index INTEGER,
    active INTEGER NOT NULL
        CHECK (active IN (0, 1))
);

CREATE TABLE content (
    ref_id INTEGER PRIMARY KEY,
    family TEXT NOT NULL
        CHECK (family IN ('news', 'document', 'youtube')),
    record_type TEXT NOT NULL,
    source_key TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL,
    chunk_index INTEGER,

    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT,
    publisher TEXT COLLATE NOCASE,
    section TEXT,
    topic TEXT,

    -- Denormalized searchable term string for FTS.
    topics TEXT NOT NULL DEFAULT '',

    -- Plain searchable text.
    text TEXT NOT NULL,

    -- Canonical presentation Markdown; deliberately excluded from FTS.
    display_markdown TEXT NOT NULL DEFAULT '',

    priority REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}',

    FOREIGN KEY (ref_id)
        REFERENCES ref_registry(ref_id)
);

CREATE INDEX idx_content_family
    ON content(family);

CREATE INDEX idx_content_record_type
    ON content(record_type);

CREATE INDEX idx_content_source_id
    ON content(source_id);

CREATE INDEX idx_content_published_at
    ON content(published_at);

CREATE INDEX idx_content_priority
    ON content(priority);

CREATE INDEX idx_content_section
    ON content(section);

CREATE INDEX idx_content_topic
    ON content(topic);

CREATE TABLE content_terms (
    ref_id INTEGER NOT NULL,
    kind TEXT NOT NULL
        CHECK (kind IN ('topic', 'tag', 'playlist', 'section')),
    value TEXT NOT NULL,

    PRIMARY KEY (ref_id, kind, value),

    FOREIGN KEY (ref_id)
        REFERENCES content(ref_id)
        ON DELETE CASCADE
) WITHOUT ROWID;

CREATE INDEX idx_content_terms_lookup
    ON content_terms(kind, value, ref_id);

-- Reserved for the later TF-IDF top-24 neighbor index.
CREATE TABLE related_content (
    ref_id INTEGER NOT NULL,
    related_ref_id INTEGER NOT NULL,
    rank INTEGER NOT NULL
        CHECK (rank BETWEEN 1 AND 24),

    PRIMARY KEY (ref_id, rank),

    UNIQUE (ref_id, related_ref_id),

    FOREIGN KEY (ref_id)
        REFERENCES content(ref_id)
        ON DELETE CASCADE,

    FOREIGN KEY (related_ref_id)
        REFERENCES content(ref_id)
        ON DELETE CASCADE,

    CHECK (ref_id <> related_ref_id)
) WITHOUT ROWID;

CREATE INDEX idx_related_content_reverse
    ON related_content(related_ref_id, ref_id);

CREATE VIRTUAL TABLE fts_content
USING fts5(
    title,
    text,
    publisher,
    topics,
    content='content',
    content_rowid='ref_id',
    tokenize='porter unicode61'
);
"""


def check_fts5(
    connection: sqlite3.Connection,
) -> None:
    try:
        connection.execute(
            "CREATE VIRTUAL TABLE temp.__fts5_check USING fts5(x)"
        )

        connection.execute(
            "DROP TABLE temp.__fts5_check"
        )

    except sqlite3.OperationalError as exc:
        raise RuntimeError(
            "This Python/SQLite build does not include FTS5."
        ) from exc


def create_database(
    path: Path,
    registry_rows: list[dict[str, Any]],
    content_rows: list[dict[str, Any]],
    term_rows: list[tuple[int, str, str]],
    build_meta: dict[str, str],
) -> None:
    if path.exists():
        path.unlink()

    connection = sqlite3.connect(
        path
    )

    try:
        connection.execute(
            "PRAGMA foreign_keys = ON"
        )

        connection.execute(
            "PRAGMA journal_mode = DELETE"
        )

        connection.execute(
            "PRAGMA synchronous = NORMAL"
        )

        connection.execute(
            "PRAGMA temp_store = MEMORY"
        )

        check_fts5(
            connection
        )

        connection.executescript(
            SCHEMA_SQL
        )

        registry_ref_ids = {
            int(row["ref_id"])
            for row in registry_rows
        }

        content_ref_ids = {
            int(row["ref_id"])
            for row in content_rows
        }

        term_ref_ids = {
            int(ref_id)
            for ref_id, _, _ in term_rows
        }

        content_without_registry = sorted(
            content_ref_ids - registry_ref_ids
        )

        terms_without_content = sorted(
            term_ref_ids - content_ref_ids
        )

        if content_without_registry:
            raise RuntimeError(
                "Content rows reference ref_ids missing from ref_registry: "
                f"{content_without_registry[:25]}"
            )

        if terms_without_content:
            raise RuntimeError(
                "content_terms rows reference ref_ids missing from content: "
                f"{terms_without_content[:25]}"
            )

        with connection:
            connection.executemany(
                """
                INSERT INTO ref_registry (
                    ref_id,
                    family,
                    record_type,
                    source_key,
                    source_id,
                    chunk_index,
                    active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(row["ref_id"]),
                        row["family"],
                        row["record_type"],
                        row["source_key"],
                        row["source_id"],
                        row.get("chunk_index"),
                        1
                        if row.get("active")
                        else 0,
                    )
                    for row in registry_rows
                ],
            )

            connection.executemany(
                """
                INSERT INTO content (
                    ref_id,
                    family,
                    record_type,
                    source_key,
                    source_id,
                    chunk_index,
                    title,
                    url,
                    published_at,
                    publisher,
                    section,
                    topic,
                    topics,
                    text,
                    display_markdown,
                    priority,
                    metadata_json
                )
                VALUES (
                    :ref_id,
                    :family,
                    :record_type,
                    :source_key,
                    :source_id,
                    :chunk_index,
                    :title,
                    :url,
                    :published_at,
                    :publisher,
                    :section,
                    :topic,
                    :topics,
                    :text,
                    :display_markdown,
                    :priority,
                    :metadata_json
                )
                """,
                content_rows,
            )

            connection.executemany(
                """
                INSERT INTO content_terms (
                    ref_id,
                    kind,
                    value
                )
                VALUES (?, ?, ?)
                """,
                term_rows,
            )

            connection.executemany(
                """
                INSERT INTO build_meta (
                    key,
                    value
                )
                VALUES (?, ?)
                """,
                sorted(
                    build_meta.items()
                ),
            )

            # Rebuild external-content FTS from content.
            connection.execute(
                "INSERT INTO fts_content(fts_content) VALUES('rebuild')"
            )

        connection.execute(
            "PRAGMA optimize"
        )

        connection.commit()

    finally:
        connection.close()


# ============================================================================
# Validation
# ============================================================================

def validate_database(
    path: Path,
    expected_registry_rows: int,
    expected_active_refs: int,
    expected_news: int,
    expected_documents: int,
    expected_youtube: int,
) -> dict[str, Any]:
    connection = sqlite3.connect(
        path
    )

    connection.row_factory = sqlite3.Row

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchall()

        integrity_values = [
            row[0]
            for row in integrity
        ]

        foreign_key_rows = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()

        counts = {
            "registry":
                connection.execute(
                    "SELECT COUNT(*) FROM ref_registry"
                ).fetchone()[0],

            "registry_active":
                connection.execute(
                    "SELECT COUNT(*) FROM ref_registry WHERE active = 1"
                ).fetchone()[0],

            "content":
                connection.execute(
                    "SELECT COUNT(*) FROM content"
                ).fetchone()[0],

            "news":
                connection.execute(
                    "SELECT COUNT(*) FROM content WHERE family = 'news'"
                ).fetchone()[0],

            "document":
                connection.execute(
                    "SELECT COUNT(*) FROM content WHERE family = 'document'"
                ).fetchone()[0],

            "youtube":
                connection.execute(
                    "SELECT COUNT(*) FROM content WHERE family = 'youtube'"
                ).fetchone()[0],

            "fts":
                connection.execute(
                    "SELECT COUNT(*) FROM fts_content"
                ).fetchone()[0],

            "terms":
                connection.execute(
                    "SELECT COUNT(*) FROM content_terms"
                ).fetchone()[0],

            "related":
                connection.execute(
                    "SELECT COUNT(*) FROM related_content"
                ).fetchone()[0],
        }

        missing_content = connection.execute(
            """
            SELECT COUNT(*)
            FROM ref_registry r
            LEFT JOIN content c
                ON c.ref_id = r.ref_id
            WHERE r.active = 1
              AND c.ref_id IS NULL
            """
        ).fetchone()[0]

        orphan_content = connection.execute(
            """
            SELECT COUNT(*)
            FROM content c
            LEFT JOIN ref_registry r
                ON r.ref_id = c.ref_id
            WHERE r.ref_id IS NULL
               OR r.active <> 1
            """
        ).fetchone()[0]

        news_id_mismatch = connection.execute(
            """
            SELECT COUNT(*)
            FROM ref_registry
            WHERE family = 'news'
              AND ref_id <> CAST(source_id AS INTEGER)
            """
        ).fetchone()[0]

        range_mismatch = connection.execute(
            """
            SELECT COUNT(*)
            FROM ref_registry
            WHERE
                (family = 'news'
                    AND NOT (ref_id BETWEEN 1 AND 99999))
                OR
                (family = 'document'
                    AND NOT (ref_id BETWEEN 100000 AND 999999))
                OR
                (family = 'youtube'
                    AND ref_id < 1000000)
            """
        ).fetchone()[0]

        wingmakers_refs = connection.execute(
            """
            SELECT COUNT(*)
            FROM ref_registry
            WHERE lower(source_key) LIKE '%wingmakers%'
               OR lower(source_id) LIKE '%wingmakers%'
            """
        ).fetchone()[0]

        duplicate_content_keys = connection.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT source_key
                FROM content
                GROUP BY source_key
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        wrong_page_publishers = connection.execute(
            """
            SELECT COUNT(*)
            FROM content
            WHERE record_type = 'page_chunk'
              AND publisher <> 'WTK Page' COLLATE NOCASE
            """
        ).fetchone()[0]

        wrong_substack_publishers = connection.execute(
            """
            SELECT COUNT(*)
            FROM content
            WHERE record_type = 'substack_chunk'
              AND publisher <> 'PEERS Substack' COLLATE NOCASE
            """
        ).fetchone()[0]

        wrong_youtube_publishers = connection.execute(
            """
            SELECT COUNT(*)
            FROM content
            WHERE record_type = 'youtube_chunk'
              AND publisher <> 'PEERS Conscious Media' COLLATE NOCASE
            """
        ).fetchone()[0]

        errors = []

        if integrity_values != ["ok"]:
            errors.append(
                "PRAGMA integrity_check did not return exactly 'ok'."
            )

        if foreign_key_rows:
            errors.append(
                f"PRAGMA foreign_key_check returned "
                f"{len(foreign_key_rows)} rows."
            )

        expected = {
            "registry":
                expected_registry_rows,
            "registry_active":
                expected_active_refs,
            "content":
                expected_active_refs,
            "news":
                expected_news,
            "document":
                expected_documents,
            "youtube":
                expected_youtube,
            "fts":
                expected_active_refs,
            "related":
                0,
        }

        for key, expected_value in expected.items():
            if counts[key] != expected_value:
                errors.append(
                    f"{key} count {counts[key]} != expected {expected_value}"
                )

        if missing_content:
            errors.append(
                f"{missing_content} active registry refs lack content rows."
            )

        if orphan_content:
            errors.append(
                f"{orphan_content} content rows do not map to active refs."
            )

        if news_id_mismatch:
            errors.append(
                f"{news_id_mismatch} news refs violate ref_id == ArticleID."
            )

        if range_mismatch:
            errors.append(
                f"{range_mismatch} registry rows violate ref namespaces."
            )

        if wingmakers_refs:
            errors.append(
                f"{wingmakers_refs} WingMakers refs remain in the database."
            )

        if duplicate_content_keys:
            errors.append(
                f"{duplicate_content_keys} duplicate content source_keys."
            )

        if wrong_page_publishers:
            errors.append(
                f"{wrong_page_publishers} page chunks do not use "
                "'WTK Page' publisher."
            )

        if wrong_substack_publishers:
            errors.append(
                f"{wrong_substack_publishers} Substack chunks do not use "
                "'PEERS Substack' publisher."
            )

        if wrong_youtube_publishers:
            errors.append(
                f"{wrong_youtube_publishers} YouTube chunks do not use "
                "'PEERS Conscious Media' publisher."
            )

        return {
            "valid":
                not errors,
            "errors":
                errors,
            "integrity_check":
                integrity_values,
            "foreign_key_errors":
                len(
                    foreign_key_rows
                ),
            "counts":
                counts,
            "checks": {
                "missing_active_content":
                    missing_content,
                "orphan_content":
                    orphan_content,
                "news_id_mismatch":
                    news_id_mismatch,
                "ref_range_mismatch":
                    range_mismatch,
                "wingmakers_refs":
                    wingmakers_refs,
                "duplicate_content_source_keys":
                    duplicate_content_keys,
                "wrong_page_publishers":
                    wrong_page_publishers,
                "wrong_substack_publishers":
                    wrong_substack_publishers,
                "wrong_youtube_publishers":
                    wrong_youtube_publishers,
            },
        }

    finally:
        connection.close()


# ============================================================================
# CLI / main
# ============================================================================

def args():
    parser = ArgumentParser(
        description=(
            "Build WantToKnow.info SQLite + FTS5 search database."
        )
    )

    parser.add_argument(
        "--site-root",
        type=Path,
        default=DEFAULT_SITE_ROOT,
    )

    parser.add_argument(
        "--news-source",
        type=Path,
        default=None,
        help=(
            "Optional deliberate override for the full news master. "
            "Default: src/site/data/wtk_articles_master.jsonl"
        ),
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Optional SQLite output override."
        ),
    )

    return parser.parse_args()


def main() -> None:
    a = args()
    root = a.site_root

    data_root = (
        root
        / "src"
        / "site"
        / "data"
    )

    corpus = (
        data_root
        / "corpus"
    )

    search_dir = (
        data_root
        / "search"
    )

    article_index_path = (
        data_root
        / "article-index.jsonl"
    )

    document_path = (
        corpus
        / "document-chunks-v1.jsonl"
    )

    youtube_path = (
        corpus
        / "youtube-search-chunks-v1.jsonl"
    )

    registry_path = (
        corpus
        / "ref-registry-v1.jsonl"
    )

    output_path = (
        a.output
        or (
            search_dir
            / "wanttoknow-search.sqlite"
        )
    )

    report_path = (
        root
        / "reports"
        / "build"
        / "search-db-build.json"
    )

    required = [
        article_index_path,
        document_path,
        youtube_path,
        registry_path,
    ]

    for path in required:
        if not path.exists():
            raise FileNotFoundError(
                f"Missing required input: {path}"
            )

    news_source_path = (
        a.news_source
        or (
            data_root
            / "wtk_articles_master.jsonl"
        )
    )

    if not news_source_path.exists():
        raise FileNotFoundError(
            "Canonical news master not found: "
            f"{news_source_path}"
        )

    print()
    print("Loading frozen search corpora...")
    print(
        f"News full-text source:    {news_source_path}"
    )

    article_index = load_jsonl(
        article_index_path
    )

    document_rows = load_jsonl(
        document_path
    )

    youtube_rows = load_jsonl(
        youtube_path
    )

    registry_rows = load_jsonl(
        registry_path
    )

    news_master_rows = load_table(
        news_source_path
    )

    print("Normalizing unified content rows...")

    news_content, news_terms = (
        build_news_content(
            registry_rows,
            article_index,
            news_master_rows,
        )
    )

    document_content, document_terms = (
        build_document_content(
            document_rows
        )
    )

    youtube_content, youtube_terms = (
        build_youtube_content(
            youtube_rows
        )
    )

    content_rows = (
        news_content
        + document_content
        + youtube_content
    )

    term_rows = (
        news_terms
        + document_terms
        + youtube_terms
    )

    active_registry = [
        row
        for row in registry_rows
        if row.get(
            "active"
        )
    ]

    active_ref_ids = {
        int(
            row["ref_id"]
        )
        for row in active_registry
    }

    content_ref_ids = {
        int(
            row["ref_id"]
        )
        for row in content_rows
    }

    if active_ref_ids != content_ref_ids:
        missing = sorted(
            active_ref_ids
            - content_ref_ids
        )

        extra = sorted(
            content_ref_ids
            - active_ref_ids
        )

        raise RuntimeError(
            "Unified content set does not exactly match active registry. "
            f"missing={len(missing)}, extra={len(extra)}, "
            f"missing_examples={missing[:20]}, "
            f"extra_examples={extra[:20]}"
        )

    if len(content_ref_ids) != len(content_rows):
        raise RuntimeError(
            "Duplicate ref_id in normalized content rows."
        )

    search_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    tmp_path = output_path.with_suffix(
        output_path.suffix
        + ".tmp"
    )

    if tmp_path.exists():
        tmp_path.unlink()

    input_paths = {
        "article_index":
            article_index_path,
        "news_source":
            news_source_path,
        "document_chunks":
            document_path,
        "youtube_search_chunks":
            youtube_path,
        "ref_registry":
            registry_path,
    }

    build_meta = {
        "schema_version":
            "1",
        "built_at":
            now_iso(),
        "site_origin":
            SITE_ORIGIN,
        "news_source":
            str(
                news_source_path
            ),
        "active_refs":
            str(
                len(
                    active_registry
                )
            ),
        "news_refs":
            str(
                len(
                    news_content
                )
            ),
        "document_refs":
            str(
                len(
                    document_content
                )
            ),
        "youtube_refs":
            str(
                len(
                    youtube_content
                )
            ),
        "publisher_page":
            "WTK Page",
        "publisher_substack":
            "PEERS Substack",
        "publisher_youtube":
            "PEERS Conscious Media",
    }

    for name, path in input_paths.items():
        build_meta[
            f"sha256_{name}"
        ] = file_sha256(
            path
        )

    print("Building SQLite + FTS5...")

    create_database(
        tmp_path,
        registry_rows,
        sorted(
            content_rows,
            key=lambda row:
                row[
                    "ref_id"
                ],
        ),
        sorted(
            set(
                term_rows
            )
        ),
        build_meta,
    )

    validation = validate_database(
        tmp_path,
        expected_registry_rows=len(
            registry_rows
        ),
        expected_active_refs=len(
            active_registry
        ),
        expected_news=len(
            news_content
        ),
        expected_documents=len(
            document_content
        ),
        expected_youtube=len(
            youtube_content
        ),
    )

    report = {
        "build_type":
            "search-db-v1",
        "built_at":
            now_iso(),
        "output":
            str(
                output_path
            ),
        "temporary_output":
            str(
                tmp_path
            ),
        "inputs": {
            name: {
                "path":
                    str(
                        path
                    ),
                "sha256":
                    build_meta[
                        f"sha256_{name}"
                    ],
            }
            for name, path in input_paths.items()
        },
        "counts": {
            "registry_rows":
                len(
                    registry_rows
                ),
            "active_refs":
                len(
                    active_registry
                ),
            "news":
                len(
                    news_content
                ),
            "documents":
                len(
                    document_content
                ),
            "youtube":
                len(
                    youtube_content
                ),
            "content_terms":
                len(
                    set(
                        term_rows
                    )
                ),
        },
        "validation":
            validation,
    }

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    if not validation[
        "valid"
    ]:
        print()
        print("SEARCH DB BUILD FAILED")
        print(
            f"Validation errors: "
            f"{len(validation['errors']):,}"
        )

        for error in validation[
            "errors"
        ]:
            print(
                f"  - {error}"
            )

        print(
            f"Report: {report_path}"
        )

        raise SystemExit(
            1
        )

    # Atomic replacement only after all validation passes.
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    os.replace(
        tmp_path,
        output_path,
    )

    size_mb = (
        output_path.stat().st_size
        / 1024
        / 1024
    )

    print()
    print("======================================")
    print("SEARCH DATABASE BUILD COMPLETE")
    print("======================================")
    print(
        f"Registry rows:            "
        f"{len(registry_rows):,}"
    )
    print(
        f"Active refs/content:      "
        f"{len(active_registry):,}"
    )
    print(
        f"News:                     "
        f"{len(news_content):,}"
    )
    print(
        f"Document chunks:          "
        f"{len(document_content):,}"
    )
    print(
        f"YouTube chunks:           "
        f"{len(youtube_content):,}"
    )
    print(
        f"Content terms:            "
        f"{len(set(term_rows)):,}"
    )
    print(
        f"FTS rows:                 "
        f"{validation['counts']['fts']:,}"
    )
    print(
        f"Related rows:             "
        f"{validation['counts']['related']:,}"
    )
    print(
        f"Integrity check:           "
        f"{validation['integrity_check'][0]}"
    )
    print(
        f"Foreign-key errors:       "
        f"{validation['foreign_key_errors']:,}"
    )
    print(
        f"WingMakers refs:          "
        f"{validation['checks']['wingmakers_refs']:,}"
    )
    print(
        f"Database size:            "
        f"{size_mb:.2f} MiB"
    )
    print()
    print(
        f"Database: {output_path}"
    )
    print(
        f"Build report: {report_path}"
    )


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        raise

    except SystemExit:
        raise

    except Exception as exc:
        print()
        print(
            "SEARCH DB BUILD FAILED",
            file=sys.stderr,
        )
        print(
            str(exc),
            file=sys.stderr,
        )
        raise
