#!/usr/bin/env python3
"""
Freeze and validate the WantToKnow.info derived search/reference layer.

Canonical/derived inputs are READ ONLY.

Inputs
------
src/site/data/corpus/document-chunks-v1.jsonl
src/site/data/corpus/youtube-search-chunks-v1.jsonl
src/site/data/corpus/youtube-chunks-v1.jsonl
src/site/data/corpus/ref-registry-v1.jsonl
src/site/data/article-index.jsonl

Writes schemas
--------------
config/schemas/document-chunk-v1.schema.json
config/schemas/youtube-search-chunk-v1.schema.json
config/schemas/ref-registry-v1.schema.json

Writes reports
--------------
reports/migration/document-chunk-v1-validation.json
reports/migration/youtube-search-chunk-v1-validation.json
reports/migration/ref-registry-v1-validation.json
reports/migration/search-layer-v1-validation.json

Validation includes
-------------------
Document chunks
  - schema validation
  - unique ref_id/source_key
  - ref_id in 100000..999999
  - word_count exactly matches text
  - hard maximum 320 words
  - short chunks carry QC flag
  - SHA-256 matches
  - source_key matches record type/source/chunk index
  - chunk indexes sequential per parent
  - source word ranges contiguous/lossless per parent
  - source_word_count consistent per parent
  - registry row exactly matches chunk identity

YouTube search chunks
  - schema validation
  - unique ref_id/source_key
  - ref_id >= 1000000
  - word_count exactly matches text
  - hard maximum 320 words
  - SHA-256 and timestamp URL integrity
  - source_key matches video/chunk index
  - sequential chunk indexes per video
  - registry row exactly matches chunk identity
  - derived search record exactly matches frozen canonical YouTube chunk
    after removing search-layer-only fields

Registry
  - unique ref_id and source_key
  - family agrees with numeric namespace
  - news ref_id == ArticleID
  - active news rows exactly match article-index.jsonl
  - active document rows exactly match document-chunks-v1.jsonl
  - active YouTube rows exactly match youtube-search-chunks-v1.jsonl
  - source_key agrees with record_type/source_id/chunk_index
  - inactive IDs remain structurally valid and reserved

Run
---
python scripts/freeze-search-schemas.py
"""

from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import re
import sys

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError as exc:
    raise SystemExit(
        "\nMissing dependency: jsonschema\n"
        "Install with:\n"
        "  python -m pip install jsonschema\n"
    ) from exc


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_SITE_ROOT = Path("/mnt/c/datasources/wanttoknow-site")

DOC_MIN = 260
DOC_MAX = 320
YOUTUBE_MAX = 320

NEWS_REF_MIN = 1
NEWS_REF_MAX = 99_999
DOCUMENT_REF_MIN = 100_000
DOCUMENT_REF_MAX = 999_999
YOUTUBE_REF_MIN = 1_000_000

SHA256_RE = r"^[0-9a-f]{64}$"
YOUTUBE_ID_RE = r"^[A-Za-z0-9_-]{11}$"
YOUTUBE_CHUNK_ID_RE = (
    r"^youtube:[A-Za-z0-9_-]{11}:chunk:[0-9]{4,}$"
)
YOUTUBE_SOURCE_KEY_RE = (
    r"^youtube:[A-Za-z0-9_-]{11}:chunk:[0-9]{4,}$"
)
DOCUMENT_SOURCE_KEY_RE = (
    r"^(?:page:.+|substack:[0-9]+):chunk:[0-9]{4,}$"
)
TIMESTAMP_RE = r"^[0-9]+:[0-5][0-9]:[0-5][0-9]$"
WORD_RE = re.compile(r"\S+")


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


def word_count(text: str) -> int:
    return len(WORD_RE.findall(text or ""))


def sha256_text(text: str) -> str:
    return hashlib.sha256(
        (text or "").encode("utf-8")
    ).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path}:{line_no}: invalid JSON: {exc}"
                ) from exc

            if not isinstance(row, dict):
                raise RuntimeError(
                    f"{path}:{line_no}: expected a JSON object."
                )

            row["_validation_line"] = line_no
            rows.append(row)

    return rows


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if not key.startswith("_validation_")
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def schema_errors(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
    )

    errors = []

    for row in rows:
        line = row["_validation_line"]
        rid = row.get("ref_id")
        source_key = row.get("source_key")

        for error in validator.iter_errors(clean_row(row)):
            path = ".".join(
                str(part)
                for part in error.absolute_path
            )

            errors.append({
                "line": line,
                "ref_id": rid,
                "source_key": source_key,
                "path": path or "$",
                "message": error.message,
            })

    return errors


def duplicate_errors(
    rows: list[dict[str, Any]],
    field: str,
) -> list[dict[str, Any]]:
    seen: dict[Any, int] = {}
    errors = []

    for row in rows:
        value = row.get(field)
        line = row["_validation_line"]

        if value in seen:
            errors.append({
                "line": line,
                "ref_id": row.get("ref_id"),
                "source_key": row.get("source_key"),
                "message": (
                    f"duplicate {field}={value!r}; "
                    f"first seen on line {seen[value]}"
                ),
            })
        else:
            seen[value] = line

    return errors


def qc_summary(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    counter = Counter()

    for row in rows:
        for flag in row.get("qc_flags") or []:
            counter[str(flag)] += 1

    return dict(sorted(counter.items()))


def family_for_ref(ref_id: int) -> str:
    if NEWS_REF_MIN <= ref_id <= NEWS_REF_MAX:
        return "news"

    if DOCUMENT_REF_MIN <= ref_id <= DOCUMENT_REF_MAX:
        return "document"

    if ref_id >= YOUTUBE_REF_MIN:
        return "youtube"

    return "reserved"


def article_id(row: dict[str, Any]) -> int:
    value = row.get("id")

    if value is None:
        value = row.get("article_id")

    if value is None:
        value = row.get("ArticleId")

    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"Invalid article ID in article-index.jsonl: {value!r}"
        ) from exc

    if not (NEWS_REF_MIN <= result <= NEWS_REF_MAX):
        raise RuntimeError(
            f"ArticleID {result} falls outside news ref_id namespace."
        )

    return result


# ============================================================================
# JSON Schema fragments
# ============================================================================

nullable_string = {
    "type": ["string", "null"],
}

nullable_number = {
    "type": ["number", "null"],
}

string_array = {
    "type": "array",
    "items": {"type": "string"},
}

unique_string_array = {
    "type": "array",
    "items": {"type": "string"},
    "uniqueItems": True,
}

qc_flags_schema = {
    "type": "array",
    "items": {
        "type": "string",
        "minLength": 1,
    },
    "uniqueItems": True,
}

heading_paths_schema = {
    "type": "array",
    "items": {
        "type": "array",
        "items": {"type": "string"},
    },
}


# ============================================================================
# Frozen schemas
# ============================================================================

DOCUMENT_CHUNK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": (
        "https://wanttoknow.info/schemas/"
        "document-chunk-v1.schema.json"
    ),
    "title": "WantToKnow.info DocumentChunk v1",
    "type": "object",
    "required": [
        "schema_version",
        "record_type",
        "ref_id",
        "source_key",
        "source_id",
        "chunk_index",
        "title",
        "url",
        "section",
        "topic",
        "topics",
        "tags",
        "heading",
        "headings",
        "heading_paths",
        "published_at",
        "updated_at",
        "priority",
        "word_count",
        "text",
        "text_sha256",
        "source_word_start",
        "source_word_end",
        "source_word_count",
        "qc_flags",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "record_type": {
            "type": "string",
            "enum": [
                "page_chunk",
                "substack_chunk",
            ],
        },
        "ref_id": {
            "type": "integer",
            "minimum": DOCUMENT_REF_MIN,
            "maximum": DOCUMENT_REF_MAX,
        },
        "source_key": {
            "type": "string",
            "pattern": DOCUMENT_SOURCE_KEY_RE,
        },
        "source_id": {
            "type": "string",
            "minLength": 1,
        },
        "chunk_index": {
            "type": "integer",
            "minimum": 0,
        },
        "title": {
            "type": "string",
        },
        "url": {
            "type": "string",
        },
        "section": nullable_string,
        "topic": nullable_string,
        "topics": string_array,
        "tags": string_array,
        "heading": nullable_string,
        "headings": string_array,
        "heading_paths": heading_paths_schema,
        "published_at": nullable_string,
        "updated_at": nullable_string,
        "priority": nullable_number,
        "word_count": {
            "type": "integer",
            "minimum": 1,
            "maximum": DOC_MAX,
        },
        "text": {
            "type": "string",
            "minLength": 1,
        },
        "text_sha256": {
            "type": "string",
            "pattern": SHA256_RE,
        },
        "source_word_start": {
            "type": "integer",
            "minimum": 0,
        },
        "source_word_end": {
            "type": "integer",
            "minimum": 0,
        },
        "source_word_count": {
            "type": "integer",
            "minimum": 1,
        },
        "qc_flags": qc_flags_schema,
    },
    "additionalProperties": False,
}


YOUTUBE_SEARCH_CHUNK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": (
        "https://wanttoknow.info/schemas/"
        "youtube-search-chunk-v1.schema.json"
    ),
    "title": "WantToKnow.info YouTubeSearchChunk v1",
    "type": "object",
    "required": [
        "schema_version",
        "ref_id",
        "source_key",
        "id",
        "record_type",
        "video_id",
        "chunk_index",
        "word_count",
        "timestamp_seconds",
        "timestamp_formatted",
        "timestamp_url",
        "end_seconds",
        "source_snippet_start",
        "source_snippet_end",
        "text",
        "text_sha256",
        "qc_flags",
        "video_title",
        "video_url",
        "published_at",
        "caption_type",
        "caption_language",
        "playlists",
        "topics",
        "priority",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "ref_id": {
            "type": "integer",
            "minimum": YOUTUBE_REF_MIN,
        },
        "source_key": {
            "type": "string",
            "pattern": YOUTUBE_SOURCE_KEY_RE,
        },
        "id": {
            "type": "string",
            "pattern": YOUTUBE_CHUNK_ID_RE,
        },
        "record_type": {
            "const": "youtube_chunk",
        },
        "video_id": {
            "type": "string",
            "pattern": YOUTUBE_ID_RE,
        },
        "chunk_index": {
            "type": "integer",
            "minimum": 0,
        },
        "word_count": {
            "type": "integer",
            "minimum": 1,
            "maximum": YOUTUBE_MAX,
        },
        "timestamp_seconds": {
            "type": "integer",
            "minimum": 0,
        },
        "timestamp_formatted": {
            "type": "string",
            "pattern": TIMESTAMP_RE,
        },
        "timestamp_url": {
            "type": "string",
            "format": "uri",
        },
        "end_seconds": {
            "type": "number",
            "minimum": 0,
        },
        "source_snippet_start": {
            "type": "integer",
            "minimum": 0,
        },
        "source_snippet_end": {
            "type": "integer",
            "minimum": 0,
        },
        "text": {
            "type": "string",
            "minLength": 1,
        },
        "text_sha256": {
            "type": "string",
            "pattern": SHA256_RE,
        },
        "qc_flags": qc_flags_schema,
        "video_title": {
            "type": "string",
            "minLength": 1,
        },
        "video_url": {
            "type": "string",
            "format": "uri",
        },
        "published_at": nullable_string,
        "caption_type": nullable_string,
        "caption_language": nullable_string,
        "playlists": string_array,
        "topics": string_array,
        "priority": nullable_number,
    },
    "additionalProperties": False,
}


REF_REGISTRY_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": (
        "https://wanttoknow.info/schemas/"
        "ref-registry-v1.schema.json"
    ),
    "title": "WantToKnow.info RefRegistry v1",
    "type": "object",
    "required": [
        "schema_version",
        "ref_id",
        "family",
        "record_type",
        "source_key",
        "source_id",
        "chunk_index",
        "active",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "ref_id": {
            "type": "integer",
            "minimum": NEWS_REF_MIN,
        },
        "family": {
            "type": "string",
            "enum": [
                "news",
                "document",
                "youtube",
            ],
        },
        "record_type": {
            "type": "string",
            "enum": [
                "news",
                "page_chunk",
                "substack_chunk",
                "youtube_chunk",
            ],
        },
        "source_key": {
            "type": "string",
            "minLength": 1,
        },
        "source_id": {
            "type": "string",
            "minLength": 1,
        },
        "chunk_index": {
            "type": ["integer", "null"],
            "minimum": 0,
        },
        "active": {
            "type": "boolean",
        },
    },
    "additionalProperties": False,
}


# ============================================================================
# Source-key helpers
# ============================================================================

def expected_document_source_key(
    row: dict[str, Any],
) -> str | None:
    record_type = row.get("record_type")
    source_id = row.get("source_id")
    chunk_index = row.get("chunk_index")

    if not isinstance(source_id, str):
        return None

    if not isinstance(chunk_index, int):
        return None

    suffix = f"chunk:{chunk_index + 1:04d}"

    if record_type == "page_chunk":
        return f"page:{source_id}:{suffix}"

    if record_type == "substack_chunk":
        # source_id already uses substack:<post_id>
        return f"{source_id}:{suffix}"

    return None


def expected_youtube_source_key(
    video_id: Any,
    chunk_index: Any,
) -> str | None:
    if not isinstance(video_id, str):
        return None

    if not isinstance(chunk_index, int):
        return None

    return (
        f"youtube:{video_id}:"
        f"chunk:{chunk_index + 1:04d}"
    )


def expected_registry_source_key(
    row: dict[str, Any],
) -> str | None:
    family = row.get("family")
    record_type = row.get("record_type")
    source_id = row.get("source_id")
    chunk_index = row.get("chunk_index")

    if family == "news" and record_type == "news":
        if chunk_index is not None:
            return None

        return f"news:{source_id}"

    if family == "document":
        return expected_document_source_key(row)

    if family == "youtube" and record_type == "youtube_chunk":
        return expected_youtube_source_key(
            source_id,
            chunk_index,
        )

    return None


# ============================================================================
# Registry semantic validation
# ============================================================================

def validate_registry_semantics(
    registry: list[dict[str, Any]],
    article_index: list[dict[str, Any]],
    document_chunks: list[dict[str, Any]],
    youtube_search: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    errors = []

    errors.extend(
        duplicate_errors(
            registry,
            "ref_id",
        )
    )

    errors.extend(
        duplicate_errors(
            registry,
            "source_key",
        )
    )

    # Structural/range identity.
    for row in registry:
        line = row["_validation_line"]
        ref_id = row.get("ref_id")
        family = row.get("family")
        record_type = row.get("record_type")
        source_key = row.get("source_key")
        source_id = row.get("source_id")
        chunk_index = row.get("chunk_index")

        prefix = {
            "line": line,
            "ref_id": ref_id,
            "source_key": source_key,
        }

        if isinstance(ref_id, int):
            expected_family = family_for_ref(ref_id)

            if expected_family == "reserved":
                errors.append({
                    **prefix,
                    "message": (
                        f"ref_id {ref_id} is in an unassigned namespace"
                    ),
                })
            elif family != expected_family:
                errors.append({
                    **prefix,
                    "message": (
                        f"family={family!r} conflicts with "
                        f"ref_id namespace {expected_family!r}"
                    ),
                })

        expected_key = expected_registry_source_key(row)

        if expected_key is None:
            errors.append({
                **prefix,
                "message": (
                    "family/record_type/source_id/chunk_index "
                    "combination is invalid"
                ),
            })
        elif source_key != expected_key:
            errors.append({
                **prefix,
                "message": (
                    f"source_key mismatch: "
                    f"{source_key!r} != {expected_key!r}"
                ),
            })

        if family == "news":
            if record_type != "news":
                errors.append({
                    **prefix,
                    "message": "news family must use record_type='news'",
                })

            if chunk_index is not None:
                errors.append({
                    **prefix,
                    "message": "news registry row must have chunk_index=null",
                })

            try:
                source_article_id = int(source_id)
            except (TypeError, ValueError):
                source_article_id = None

            if (
                isinstance(ref_id, int)
                and source_article_id is not None
                and ref_id != source_article_id
            ):
                errors.append({
                    **prefix,
                    "message": (
                        "news ref_id must equal its ArticleID/source_id"
                    ),
                })

        if family == "document" and record_type not in {
            "page_chunk",
            "substack_chunk",
        }:
            errors.append({
                **prefix,
                "message": (
                    "document family must use page_chunk "
                    "or substack_chunk"
                ),
            })

        if family == "youtube" and record_type != "youtube_chunk":
            errors.append({
                **prefix,
                "message": (
                    "youtube family must use record_type='youtube_chunk'"
                ),
            })

    # Active registry sets must exactly equal current source datasets.
    expected_news = {
        f"news:{article_id(row)}": article_id(row)
        for row in article_index
    }

    active_news = {
        row["source_key"]: row["ref_id"]
        for row in registry
        if row.get("active")
        and row.get("family") == "news"
    }

    if active_news != expected_news:
        missing = sorted(
            set(expected_news) - set(active_news)
        )
        extra = sorted(
            set(active_news) - set(expected_news)
        )
        mismatched = sorted(
            key
            for key in (
                set(active_news) & set(expected_news)
            )
            if active_news[key] != expected_news[key]
        )

        errors.append({
            "line": None,
            "ref_id": None,
            "source_key": None,
            "message": (
                "active news registry does not exactly match article index; "
                f"missing={len(missing)}, extra={len(extra)}, "
                f"mismatched={len(mismatched)}"
            ),
            "examples": {
                "missing": missing[:20],
                "extra": extra[:20],
                "mismatched": mismatched[:20],
            },
        })

    expected_docs = {
        row["source_key"]: row["ref_id"]
        for row in document_chunks
    }

    active_docs = {
        row["source_key"]: row["ref_id"]
        for row in registry
        if row.get("active")
        and row.get("family") == "document"
    }

    if active_docs != expected_docs:
        missing = sorted(set(expected_docs) - set(active_docs))
        extra = sorted(set(active_docs) - set(expected_docs))
        mismatched = sorted(
            key
            for key in set(active_docs) & set(expected_docs)
            if active_docs[key] != expected_docs[key]
        )

        errors.append({
            "line": None,
            "ref_id": None,
            "source_key": None,
            "message": (
                "active document registry does not exactly match "
                "document chunk corpus; "
                f"missing={len(missing)}, extra={len(extra)}, "
                f"mismatched={len(mismatched)}"
            ),
            "examples": {
                "missing": missing[:20],
                "extra": extra[:20],
                "mismatched": mismatched[:20],
            },
        })

    expected_youtube = {
        row["source_key"]: row["ref_id"]
        for row in youtube_search
    }

    active_youtube = {
        row["source_key"]: row["ref_id"]
        for row in registry
        if row.get("active")
        and row.get("family") == "youtube"
    }

    if active_youtube != expected_youtube:
        missing = sorted(
            set(expected_youtube) - set(active_youtube)
        )
        extra = sorted(
            set(active_youtube) - set(expected_youtube)
        )
        mismatched = sorted(
            key
            for key in set(active_youtube) & set(expected_youtube)
            if active_youtube[key] != expected_youtube[key]
        )

        errors.append({
            "line": None,
            "ref_id": None,
            "source_key": None,
            "message": (
                "active YouTube registry does not exactly match "
                "YouTube search corpus; "
                f"missing={len(missing)}, extra={len(extra)}, "
                f"mismatched={len(mismatched)}"
            ),
            "examples": {
                "missing": missing[:20],
                "extra": extra[:20],
                "mismatched": mismatched[:20],
            },
        })

    return errors


# ============================================================================
# Document semantic validation
# ============================================================================

def validate_document_semantics(
    rows: list[dict[str, Any]],
    registry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    errors = []

    errors.extend(
        duplicate_errors(rows, "ref_id")
    )

    errors.extend(
        duplicate_errors(rows, "source_key")
    )

    registry_by_key = {
        row["source_key"]: row
        for row in registry
    }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        line = row["_validation_line"]
        ref_id = row.get("ref_id")
        source_key = row.get("source_key")
        source_id = row.get("source_id")
        chunk_index = row.get("chunk_index")
        wc = row.get("word_count")
        text = row.get("text") or ""

        prefix = {
            "line": line,
            "ref_id": ref_id,
            "source_key": source_key,
        }

        expected_key = expected_document_source_key(row)

        if expected_key is None or source_key != expected_key:
            errors.append({
                **prefix,
                "message": (
                    f"document source_key mismatch; expected {expected_key!r}"
                ),
            })

        actual_wc = word_count(text)

        if wc != actual_wc:
            errors.append({
                **prefix,
                "message": (
                    f"word_count mismatch: {wc} != {actual_wc}"
                ),
            })

        if isinstance(wc, int) and wc > DOC_MAX:
            errors.append({
                **prefix,
                "message": (
                    f"hard document maximum violated: {wc} > {DOC_MAX}"
                ),
            })

        flags = set(row.get("qc_flags") or [])

        if (
            isinstance(wc, int)
            and wc < DOC_MIN
            and "short_chunk_unavoidable" not in flags
        ):
            errors.append({
                **prefix,
                "message": (
                    f"{wc}-word chunk is below {DOC_MIN} "
                    "without short_chunk_unavoidable flag"
                ),
            })

        if (
            isinstance(wc, int)
            and wc >= DOC_MIN
            and "short_chunk_unavoidable" in flags
        ):
            errors.append({
                **prefix,
                "message": (
                    "short_chunk_unavoidable flag present on "
                    f"{wc}-word chunk"
                ),
            })

        if row.get("text_sha256") != sha256_text(text):
            errors.append({
                **prefix,
                "message": "text_sha256 mismatch",
            })

        start = row.get("source_word_start")
        end = row.get("source_word_end")
        total = row.get("source_word_count")

        if (
            isinstance(start, int)
            and isinstance(end, int)
            and end < start
        ):
            errors.append({
                **prefix,
                "message": "source_word_end precedes source_word_start",
            })

        if (
            isinstance(start, int)
            and isinstance(end, int)
            and isinstance(wc, int)
            and (end - start + 1) != wc
        ):
            errors.append({
                **prefix,
                "message": (
                    "source word range length does not equal word_count"
                ),
            })

        if (
            isinstance(total, int)
            and isinstance(end, int)
            and end >= total
        ):
            errors.append({
                **prefix,
                "message": (
                    "source_word_end falls outside source_word_count"
                ),
            })

        reg = registry_by_key.get(source_key)

        if reg is None:
            errors.append({
                **prefix,
                "message": "document source_key missing from ref registry",
            })
        else:
            expected_registry = {
                "ref_id": ref_id,
                "family": "document",
                "record_type": row.get("record_type"),
                "source_id": source_id,
                "chunk_index": chunk_index,
                "active": True,
            }

            for field, expected in expected_registry.items():
                if reg.get(field) != expected:
                    errors.append({
                        **prefix,
                        "message": (
                            f"registry mismatch for {field}: "
                            f"{reg.get(field)!r} != {expected!r}"
                        ),
                    })

        if isinstance(source_id, str):
            groups[source_id].append(row)

    # Parent-level sequence/provenance validation.
    for source_id, chunks in groups.items():
        chunks = sorted(
            chunks,
            key=lambda row: row.get("chunk_index", -1),
        )

        indexes = [
            row.get("chunk_index")
            for row in chunks
        ]

        expected_indexes = list(range(len(chunks)))

        if indexes != expected_indexes:
            errors.append({
                "line": None,
                "ref_id": None,
                "source_key": source_id,
                "message": (
                    "chunk indexes are not sequential from zero; "
                    f"actual={indexes[:30]}"
                ),
            })

        source_counts = {
            row.get("source_word_count")
            for row in chunks
        }

        if len(source_counts) != 1:
            errors.append({
                "line": None,
                "ref_id": None,
                "source_key": source_id,
                "message": (
                    "source_word_count differs across chunks "
                    f"for parent: {sorted(source_counts, key=str)}"
                ),
            })
            continue

        total = next(iter(source_counts))

        if not isinstance(total, int):
            continue

        expected_start = 0

        for row in chunks:
            start = row.get("source_word_start")
            end = row.get("source_word_end")

            if start != expected_start:
                errors.append({
                    "line": row["_validation_line"],
                    "ref_id": row.get("ref_id"),
                    "source_key": row.get("source_key"),
                    "message": (
                        f"non-contiguous source range: "
                        f"expected start {expected_start}, got {start}"
                    ),
                })

            if isinstance(end, int):
                expected_start = end + 1

        if expected_start != total:
            errors.append({
                "line": None,
                "ref_id": None,
                "source_key": source_id,
                "message": (
                    f"parent source coverage ends at {expected_start}; "
                    f"source_word_count={total}"
                ),
            })

    return errors


# ============================================================================
# YouTube search semantic validation
# ============================================================================

SEARCH_ONLY_YOUTUBE_FIELDS = {
    "schema_version",
    "ref_id",
    "source_key",
}


def canonical_youtube_projection(
    search_row: dict[str, Any],
) -> dict[str, Any]:
    clean = clean_row(search_row)

    return {
        key: value
        for key, value in clean.items()
        if key not in SEARCH_ONLY_YOUTUBE_FIELDS
    }


def validate_youtube_semantics(
    rows: list[dict[str, Any]],
    canonical_rows: list[dict[str, Any]],
    registry: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    errors = []

    errors.extend(
        duplicate_errors(rows, "ref_id")
    )

    errors.extend(
        duplicate_errors(rows, "source_key")
    )

    canonical_by_id = {
        row.get("id"): clean_row(row)
        for row in canonical_rows
    }

    if len(canonical_by_id) != len(canonical_rows):
        errors.append({
            "line": None,
            "ref_id": None,
            "source_key": None,
            "message": (
                "canonical youtube-chunks-v1 contains duplicate chunk IDs"
            ),
        })

    registry_by_key = {
        row["source_key"]: row
        for row in registry
    }

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        line = row["_validation_line"]
        ref_id = row.get("ref_id")
        source_key = row.get("source_key")
        video_id = row.get("video_id")
        chunk_index = row.get("chunk_index")
        chunk_id = row.get("id")
        wc = row.get("word_count")
        text = row.get("text") or ""
        seconds = row.get("timestamp_seconds")

        prefix = {
            "line": line,
            "ref_id": ref_id,
            "source_key": source_key,
        }

        expected_key = expected_youtube_source_key(
            video_id,
            chunk_index,
        )

        if expected_key is None or source_key != expected_key:
            errors.append({
                **prefix,
                "message": (
                    f"YouTube source_key mismatch; expected {expected_key!r}"
                ),
            })

        if isinstance(chunk_index, int) and isinstance(video_id, str):
            expected_id = (
                f"youtube:{video_id}:"
                f"chunk:{chunk_index + 1:04d}"
            )

            if chunk_id != expected_id:
                errors.append({
                    **prefix,
                    "message": (
                        f"YouTube chunk id mismatch: "
                        f"{chunk_id!r} != {expected_id!r}"
                    ),
                })

        actual_wc = word_count(text)

        if wc != actual_wc:
            errors.append({
                **prefix,
                "message": (
                    f"word_count mismatch: {wc} != {actual_wc}"
                ),
            })

        if isinstance(wc, int) and wc > YOUTUBE_MAX:
            errors.append({
                **prefix,
                "message": (
                    f"hard YouTube maximum violated: "
                    f"{wc} > {YOUTUBE_MAX}"
                ),
            })

        if row.get("text_sha256") != sha256_text(text):
            errors.append({
                **prefix,
                "message": "text_sha256 mismatch",
            })

        if isinstance(seconds, int) and isinstance(video_id, str):
            expected_url = (
                f"https://www.youtube.com/watch?v={video_id}"
                f"&t={seconds}s"
            )

            if row.get("timestamp_url") != expected_url:
                errors.append({
                    **prefix,
                    "message": (
                        "timestamp_url does not match "
                        "video_id/timestamp_seconds"
                    ),
                })

        start_snippet = row.get("source_snippet_start")
        end_snippet = row.get("source_snippet_end")

        if (
            isinstance(start_snippet, int)
            and isinstance(end_snippet, int)
            and end_snippet < start_snippet
        ):
            errors.append({
                **prefix,
                "message": (
                    "source_snippet_end precedes source_snippet_start"
                ),
            })

        canonical = canonical_by_id.get(chunk_id)

        if canonical is None:
            errors.append({
                **prefix,
                "message": (
                    "YouTube search chunk missing from canonical "
                    "youtube-chunks-v1"
                ),
            })
        else:
            projected = canonical_youtube_projection(row)

            if projected != canonical:
                differing_fields = sorted(
                    key
                    for key in set(projected) | set(canonical)
                    if projected.get(key) != canonical.get(key)
                )

                errors.append({
                    **prefix,
                    "message": (
                        "YouTube search chunk differs from canonical "
                        "youtube-chunks-v1"
                    ),
                    "differing_fields": differing_fields,
                })

        reg = registry_by_key.get(source_key)

        if reg is None:
            errors.append({
                **prefix,
                "message": "YouTube source_key missing from ref registry",
            })
        else:
            expected_registry = {
                "ref_id": ref_id,
                "family": "youtube",
                "record_type": "youtube_chunk",
                "source_id": video_id,
                "chunk_index": chunk_index,
                "active": True,
            }

            for field, expected in expected_registry.items():
                if reg.get(field) != expected:
                    errors.append({
                        **prefix,
                        "message": (
                            f"registry mismatch for {field}: "
                            f"{reg.get(field)!r} != {expected!r}"
                        ),
                    })

        if isinstance(video_id, str):
            groups[video_id].append(row)

    # Exact canonical set equality.
    search_ids = {
        row.get("id")
        for row in rows
    }

    canonical_ids = set(canonical_by_id)

    if search_ids != canonical_ids:
        missing = sorted(canonical_ids - search_ids)
        extra = sorted(search_ids - canonical_ids)

        errors.append({
            "line": None,
            "ref_id": None,
            "source_key": None,
            "message": (
                "YouTube search/canonical chunk ID sets differ; "
                f"missing={len(missing)}, extra={len(extra)}"
            ),
            "examples": {
                "missing": missing[:20],
                "extra": extra[:20],
            },
        })

    # Sequential indexes by video.
    for video_id, chunks in groups.items():
        chunks = sorted(
            chunks,
            key=lambda row: row.get("chunk_index", -1),
        )

        indexes = [
            row.get("chunk_index")
            for row in chunks
        ]

        expected = list(range(len(chunks)))

        if indexes != expected:
            errors.append({
                "line": None,
                "ref_id": None,
                "source_key": f"youtube:{video_id}",
                "message": (
                    "YouTube chunk indexes are not sequential from zero"
                ),
            })

    return errors


# ============================================================================
# Reporting
# ============================================================================

def report_for(
    *,
    schema_name: str,
    data_path: Path,
    rows: list[dict[str, Any]],
    schema_errs: list[dict[str, Any]],
    semantic_errs: list[dict[str, Any]],
) -> dict[str, Any]:
    errors = schema_errs + semantic_errs

    return {
        "schema": schema_name,
        "data_file": str(data_path),
        "validated_at": now_iso(),
        "records": len(rows),
        "schema_errors": len(schema_errs),
        "semantic_errors": len(semantic_errs),
        "validation_errors": len(errors),
        "valid": not errors,
        "qc_flags": qc_summary(rows),
        "errors": errors,
    }


# ============================================================================
# Main
# ============================================================================

def parse_args():
    parser = ArgumentParser()

    parser.add_argument(
        "--site-root",
        type=Path,
        default=DEFAULT_SITE_ROOT,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.site_root

    data = root / "src" / "site" / "data"
    corpus = data / "corpus"

    document_path = (
        corpus
        / "document-chunks-v1.jsonl"
    )

    youtube_search_path = (
        corpus
        / "youtube-search-chunks-v1.jsonl"
    )

    youtube_canonical_path = (
        corpus
        / "youtube-chunks-v1.jsonl"
    )

    registry_path = (
        corpus
        / "ref-registry-v1.jsonl"
    )

    article_index_path = (
        data
        / "article-index.jsonl"
    )

    required_paths = [
        document_path,
        youtube_search_path,
        youtube_canonical_path,
        registry_path,
        article_index_path,
    ]

    for path in required_paths:
        if not path.exists():
            raise RuntimeError(
                f"Missing required input: {path}"
            )

    schema_dir = (
        root
        / "config"
        / "schemas"
    )

    report_dir = (
        root
        / "reports"
        / "migration"
    )

    schema_paths = {
        "document":
            schema_dir
            / "document-chunk-v1.schema.json",
        "youtube":
            schema_dir
            / "youtube-search-chunk-v1.schema.json",
        "registry":
            schema_dir
            / "ref-registry-v1.schema.json",
    }

    report_paths = {
        "document":
            report_dir
            / "document-chunk-v1-validation.json",
        "youtube":
            report_dir
            / "youtube-search-chunk-v1-validation.json",
        "registry":
            report_dir
            / "ref-registry-v1-validation.json",
        "summary":
            report_dir
            / "search-layer-v1-validation.json",
    }

    # Freeze schema files first.
    write_json(
        schema_paths["document"],
        DOCUMENT_CHUNK_SCHEMA,
    )

    write_json(
        schema_paths["youtube"],
        YOUTUBE_SEARCH_CHUNK_SCHEMA,
    )

    write_json(
        schema_paths["registry"],
        REF_REGISTRY_SCHEMA,
    )

    print()
    print("Loading derived search layer...")

    documents = load_jsonl(
        document_path
    )

    youtube_search = load_jsonl(
        youtube_search_path
    )

    youtube_canonical = load_jsonl(
        youtube_canonical_path
    )

    registry = load_jsonl(
        registry_path
    )

    article_index = load_jsonl(
        article_index_path
    )

    print("Validating JSON Schemas...")

    document_schema_errors = schema_errors(
        documents,
        DOCUMENT_CHUNK_SCHEMA,
    )

    youtube_schema_errors = schema_errors(
        youtube_search,
        YOUTUBE_SEARCH_CHUNK_SCHEMA,
    )

    registry_schema_errors = schema_errors(
        registry,
        REF_REGISTRY_SCHEMA,
    )

    print("Validating cross-file invariants...")

    registry_semantic_errors = (
        validate_registry_semantics(
            registry,
            article_index,
            documents,
            youtube_search,
        )
    )

    document_semantic_errors = (
        validate_document_semantics(
            documents,
            registry,
        )
    )

    youtube_semantic_errors = (
        validate_youtube_semantics(
            youtube_search,
            youtube_canonical,
            registry,
        )
    )

    document_report = report_for(
        schema_name="document-chunk-v1.schema.json",
        data_path=document_path,
        rows=documents,
        schema_errs=document_schema_errors,
        semantic_errs=document_semantic_errors,
    )

    youtube_report = report_for(
        schema_name="youtube-search-chunk-v1.schema.json",
        data_path=youtube_search_path,
        rows=youtube_search,
        schema_errs=youtube_schema_errors,
        semantic_errs=youtube_semantic_errors,
    )

    registry_report = report_for(
        schema_name="ref-registry-v1.schema.json",
        data_path=registry_path,
        rows=registry,
        schema_errs=registry_schema_errors,
        semantic_errs=registry_semantic_errors,
    )

    write_json(
        report_paths["document"],
        document_report,
    )

    write_json(
        report_paths["youtube"],
        youtube_report,
    )

    write_json(
        report_paths["registry"],
        registry_report,
    )

    active_news = sum(
        row.get("active")
        and row.get("family") == "news"
        for row in registry
    )

    active_documents = sum(
        row.get("active")
        and row.get("family") == "document"
        for row in registry
    )

    active_youtube = sum(
        row.get("active")
        and row.get("family") == "youtube"
        for row in registry
    )

    inactive = sum(
        not row.get("active")
        for row in registry
    )

    summary = {
        "validation": "search-layer-v1",
        "validated_at": now_iso(),
        "records": {
            "news_active_refs": active_news,
            "document_chunks": len(documents),
            "youtube_search_chunks": len(youtube_search),
            "registry_rows": len(registry),
            "registry_active_document_refs": active_documents,
            "registry_active_youtube_refs": active_youtube,
            "registry_inactive_refs": inactive,
        },
        "ref_ranges": {
            "news": [
                NEWS_REF_MIN,
                NEWS_REF_MAX,
            ],
            "document": [
                DOCUMENT_REF_MIN,
                DOCUMENT_REF_MAX,
            ],
            "youtube": [
                YOUTUBE_REF_MIN,
                None,
            ],
        },
        "reports": {
            "document": str(report_paths["document"]),
            "youtube": str(report_paths["youtube"]),
            "registry": str(report_paths["registry"]),
        },
        "errors": {
            "document": document_report["validation_errors"],
            "youtube": youtube_report["validation_errors"],
            "registry": registry_report["validation_errors"],
        },
        "validation_errors": (
            document_report["validation_errors"]
            + youtube_report["validation_errors"]
            + registry_report["validation_errors"]
        ),
    }

    summary["valid"] = (
        summary["validation_errors"] == 0
    )

    write_json(
        report_paths["summary"],
        summary,
    )

    print()
    print("======================================")
    print("SEARCH LAYER V1 VALIDATION")
    print("======================================")
    print(
        f"News active refs:         {active_news:,}"
    )
    print(
        f"Document chunks:          {len(documents):,}"
    )
    print(
        f"YouTube search chunks:    {len(youtube_search):,}"
    )
    print(
        f"Registry rows:            {len(registry):,}"
    )
    print(
        f"Inactive registry refs:   {inactive:,}"
    )
    print()
    print(
        f"Document errors:          "
        f"{document_report['validation_errors']:,}"
    )
    print(
        f"YouTube errors:           "
        f"{youtube_report['validation_errors']:,}"
    )
    print(
        f"Registry errors:          "
        f"{registry_report['validation_errors']:,}"
    )
    print()

    if not summary["valid"]:
        print("STATUS: FAILED")
        print()
        print("Reports:")

        for path in report_paths.values():
            print(f"  {path}")

        raise SystemExit(1)

    print("STATUS: PASSED")
    print()
    print("Frozen schemas:")

    for path in schema_paths.values():
        print(f"  {path}")

    print()
    print("Validation reports:")

    for path in report_paths.values():
        print(f"  {path}")


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
            "SEARCH LAYER VALIDATION FAILED",
            file=sys.stderr,
        )
        print(
            str(exc),
            file=sys.stderr,
        )
        raise
