#!/usr/bin/env python3
"""
Freeze and validate WantToKnow.info Substack + YouTube canonical corpora.

Writes:
  config/schemas/substack-v1.schema.json
  config/schemas/youtube-v1.schema.json
  config/schemas/youtube-chunk-v1.schema.json

Validates:
  src/site/data/corpus/substack-master-v1.jsonl
  src/site/data/corpus/youtube-master-v1.jsonl
  src/site/data/corpus/youtube-chunks-v1.jsonl

Reports:
  reports/migration/substack-v1-validation.json
  reports/migration/youtube-v1-validation.json
  reports/migration/youtube-chunk-v1-validation.json

This script does NOT mutate canonical JSONL records.
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
    from jsonschema import Draft202012Validator
except ImportError as exc:
    raise SystemExit(
        "\nMissing dependency: jsonschema\n"
        "Install it with:\n"
        "  python -m pip install jsonschema\n"
    ) from exc


SITE_ROOT_DEFAULT = Path("/mnt/c/datasources/wanttoknow-site")

CHUNK_MIN = 260
CHUNK_TARGET = 290
CHUNK_MAX = 320

SHA256_RE = r"^[0-9a-f]{64}$"
YOUTUBE_ID_RE = r"^[A-Za-z0-9_-]{11}$"
YOUTUBE_RECORD_ID_RE = r"^youtube:[A-Za-z0-9_-]{11}$"
YOUTUBE_CHUNK_ID_RE = (
    r"^youtube:[A-Za-z0-9_-]{11}:chunk:[0-9]{4,}$"
)
SUBSTACK_ID_RE = r"^substack:[0-9]+$"
POST_ID_RE = r"^[0-9]+$"
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
        for line_number, line in enumerate(f, 1):
            if not line.strip():
                continue

            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path}:{line_number}: invalid JSON: {exc}"
                ) from exc

            if not isinstance(row, dict):
                raise RuntimeError(
                    f"{path}:{line_number}: JSONL row is not an object."
                )

            row["_validation_line"] = line_number
            rows.append(row)

    return rows


def strip_internal(row: dict[str, Any]) -> dict[str, Any]:
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
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def schema_errors(
    rows: list[dict[str, Any]],
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    validator = Draft202012Validator(schema)
    errors: list[dict[str, Any]] = []

    for row in rows:
        line_number = row["_validation_line"]
        clean = strip_internal(row)

        for error in validator.iter_errors(clean):
            path = ".".join(
                str(part)
                for part in error.absolute_path
            )

            errors.append({
                "line": line_number,
                "id": clean.get("id"),
                "path": path or "$",
                "message": error.message,
            })

    return errors


def unique_id_errors(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    errors = []

    for row in rows:
        record_id = row.get("id")
        line = row["_validation_line"]

        if record_id in seen:
            errors.append({
                "line": line,
                "id": record_id,
                "message": (
                    f"duplicate id; first seen on line {seen[record_id]}"
                ),
            })
        else:
            seen[record_id] = line

    return errors


def qc_summary(
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    counter = Counter()

    for row in rows:
        for flag in row.get("qc_flags") or []:
            counter[str(flag)] += 1

    return dict(sorted(counter.items()))


# ============================================================================
# Shared schema fragments
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

youtube_chunk_base_schema = {
    "type": "object",
    "required": [
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
    ],
    "properties": {
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
            "maximum": CHUNK_MAX,
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
    },
    "additionalProperties": False,
}


# ============================================================================
# Frozen schemas
# ============================================================================

SUBSTACK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://wanttoknow.info/schemas/substack-v1.schema.json",
    "title": "WantToKnow.info SubstackRecord v1",
    "type": "object",
    "required": [
        "schema_version",
        "record_type",
        "id",
        "post_id",
        "slug",
        "title",
        "title_source",
        "subtitle",
        "url",
        "published_at",
        "updated_at",
        "authors",
        "topics",
        "tags",
        "content_markdown",
        "content_text",
        "word_count",
        "images",
        "youtube_embeds",
        "links",
        "source",
        "content_sha256",
        "priority",
        "qc_flags",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "record_type": {"const": "substack"},
        "id": {
            "type": "string",
            "pattern": SUBSTACK_ID_RE,
        },
        "post_id": {
            "type": "string",
            "pattern": POST_ID_RE,
        },
        "slug": {
            "type": "string",
            "minLength": 1,
        },
        "title": {
            "type": "string",
            "minLength": 1,
        },
        "title_source": {
            "type": "string",
            "enum": [
                "metadata_csv",
                "html_title",
                "html_h1",
                "filename_slug",
            ],
        },
        "subtitle": nullable_string,
        "url": {
            "type": "string",
            "format": "uri",
        },
        "published_at": nullable_string,
        "updated_at": nullable_string,
        "authors": string_array,
        "topics": string_array,
        "tags": string_array,
        "content_markdown": {"type": "string"},
        "content_text": {"type": "string"},
        "word_count": {
            "type": "integer",
            "minimum": 0,
        },
        "images": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "url",
                    "alt",
                    "title",
                    "width",
                    "height",
                ],
                "properties": {
                    "url": {
                        "type": "string",
                        "format": "uri",
                    },
                    "alt": nullable_string,
                    "title": nullable_string,
                    "width": {
                        "type": [
                            "integer",
                            "string",
                            "null",
                        ]
                    },
                    "height": {
                        "type": [
                            "integer",
                            "string",
                            "null",
                        ]
                    },
                },
                "additionalProperties": False,
            },
        },
        "youtube_embeds": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "video_id",
                    "start_seconds",
                    "url",
                ],
                "properties": {
                    "video_id": {
                        "type": "string",
                        "pattern": YOUTUBE_ID_RE,
                    },
                    "start_seconds": {
                        "type": "integer",
                        "minimum": 0,
                    },
                    "url": {
                        "type": "string",
                        "format": "uri",
                    },
                },
                "additionalProperties": False,
            },
        },
        "links": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "url",
                    "label",
                ],
                "properties": {
                    "url": {
                        "type": "string",
                        "minLength": 1,
                    },
                    "label": {
                        "type": "string",
                    },
                },
                "additionalProperties": False,
            },
        },
        "source": {
            "type": "object",
            "required": [
                "platform",
                "publication",
                "source_file",
            ],
            "properties": {
                "platform": {"const": "substack"},
                "publication": {
                    "type": "string",
                    "minLength": 1,
                },
                "source_file": {
                    "type": "string",
                    "minLength": 1,
                },
                "metadata_file": nullable_string,
            },
            "additionalProperties": False,
        },
        "content_sha256": {
            "type": "string",
            "pattern": SHA256_RE,
        },
        "priority": nullable_number,
        "qc_flags": qc_flags_schema,
    },
    "additionalProperties": False,
}


YOUTUBE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://wanttoknow.info/schemas/youtube-v1.schema.json",
    "title": "WantToKnow.info YouTubeRecord v1",
    "type": "object",
    "required": [
        "schema_version",
        "record_type",
        "id",
        "video_id",
        "title",
        "url",
        "published_at",
        "channel",
        "description",
        "playlists",
        "topics",
        "caption_type",
        "caption_language",
        "full_transcript",
        "full_transcript_word_count",
        "timestamp_transcript_word_count",
        "timestamp_snippet_count",
        "transcript_chunks",
        "chunk_count",
        "source",
        "priority",
        "qc_flags",
    ],
    "properties": {
        "schema_version": {"const": 1},
        "record_type": {"const": "youtube"},
        "id": {
            "type": "string",
            "pattern": YOUTUBE_RECORD_ID_RE,
        },
        "video_id": {
            "type": "string",
            "pattern": YOUTUBE_ID_RE,
        },
        "title": {
            "type": "string",
            "minLength": 1,
        },
        "url": {
            "type": "string",
            "format": "uri",
        },
        "published_at": nullable_string,
        "channel": {
            "type": "object",
            "required": [
                "name",
                "channel_id",
            ],
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                },
                "channel_id": nullable_string,
            },
            "additionalProperties": False,
        },
        "description": nullable_string,
        "playlists": string_array,
        "topics": string_array,
        "caption_type": nullable_string,
        "caption_language": nullable_string,
        "full_transcript": {"type": "string"},
        "full_transcript_word_count": {
            "type": "integer",
            "minimum": 0,
        },
        "timestamp_transcript_word_count": {
            "type": "integer",
            "minimum": 0,
        },
        "timestamp_snippet_count": {
            "type": "integer",
            "minimum": 0,
        },
        "transcript_chunks": {
            "type": "array",
            "items": youtube_chunk_base_schema,
        },
        "chunk_count": {
            "type": "integer",
            "minimum": 0,
        },
        "source": {
            "type": "object",
            "required": ["platform"],
            "properties": {
                "platform": {"const": "youtube"},
            },
            "additionalProperties": False,
        },
        "priority": nullable_number,
        "qc_flags": qc_flags_schema,
    },
    "additionalProperties": False,
}


YOUTUBE_CHUNK_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://wanttoknow.info/schemas/youtube-chunk-v1.schema.json",
    "title": "WantToKnow.info YouTubeChunk v1",
    "type": "object",
    "required": (
        youtube_chunk_base_schema["required"]
        + [
            "video_title",
            "video_url",
            "published_at",
            "caption_type",
            "caption_language",
            "playlists",
            "topics",
            "priority",
        ]
    ),
    "properties": {
        **youtube_chunk_base_schema["properties"],
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


# ============================================================================
# Semantic validation
# ============================================================================

def validate_substack_semantics(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    errors = []

    for row in rows:
        line = row["_validation_line"]
        rid = row.get("id")
        post_id = str(row.get("post_id") or "")

        if rid != f"substack:{post_id}":
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    "id must equal 'substack:' + post_id"
                ),
            })

        expected_words = word_count(
            row.get("content_text") or ""
        )

        if row.get("word_count") != expected_words:
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    f"word_count mismatch: "
                    f"{row.get('word_count')} != {expected_words}"
                ),
            })

        expected_sha = sha256_text(
            row.get("content_markdown") or ""
        )

        if row.get("content_sha256") != expected_sha:
            errors.append({
                "line": line,
                "id": rid,
                "message": "content_sha256 mismatch",
            })

        for embed_index, embed in enumerate(
            row.get("youtube_embeds") or []
        ):
            vid = embed.get("video_id")
            seconds = embed.get("start_seconds")

            expected_url = (
                f"https://www.youtube.com/watch?v={vid}"
                f"&t={seconds}s"
            )

            if embed.get("url") != expected_url:
                errors.append({
                    "line": line,
                    "id": rid,
                    "message": (
                        f"youtube_embeds[{embed_index}].url "
                        f"does not match video_id/start_seconds"
                    ),
                })

    return errors


BASE_CHUNK_FIELDS = {
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
}


def chunk_base(
    row: dict[str, Any],
) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in BASE_CHUNK_FIELDS
    }


def validate_chunk_semantics(
    chunk: dict[str, Any],
    line: int | None = None,
) -> list[dict[str, Any]]:
    errors = []

    rid = chunk.get("id")
    vid = chunk.get("video_id")
    idx = chunk.get("chunk_index")
    wc = chunk.get("word_count")
    text = chunk.get("text") or ""
    seconds = chunk.get("timestamp_seconds")

    prefix = {
        "line": line,
        "id": rid,
    }

    expected_id = (
        f"youtube:{vid}:chunk:{int(idx) + 1:04d}"
        if isinstance(idx, int)
        else None
    )

    if expected_id and rid != expected_id:
        errors.append({
            **prefix,
            "message": (
                f"chunk id mismatch: expected {expected_id}"
            ),
        })

    expected_wc = word_count(text)

    if wc != expected_wc:
        errors.append({
            **prefix,
            "message": (
                f"word_count mismatch: {wc} != {expected_wc}"
            ),
        })

    if isinstance(wc, int) and wc > CHUNK_MAX:
        errors.append({
            **prefix,
            "message": (
                f"hard chunk maximum violated: {wc} > {CHUNK_MAX}"
            ),
        })

    flags = set(chunk.get("qc_flags") or [])

    if (
        isinstance(wc, int)
        and wc < CHUNK_MIN
        and "short_chunk_unavoidable" not in flags
    ):
        errors.append({
            **prefix,
            "message": (
                f"{wc}-word chunk is below {CHUNK_MIN} "
                "without short_chunk_unavoidable flag"
            ),
        })

    forbidden_flags = {
        "oversize_chunk",
        "oversize_chunk_unavoidable",
    }

    present_forbidden = sorted(
        forbidden_flags & flags
    )

    if present_forbidden:
        errors.append({
            **prefix,
            "message": (
                "obsolete/forbidden oversize chunk flags present: "
                + ", ".join(present_forbidden)
            ),
        })

    expected_sha = sha256_text(text)

    if chunk.get("text_sha256") != expected_sha:
        errors.append({
            **prefix,
            "message": "text_sha256 mismatch",
        })

    if (
        isinstance(seconds, int)
        and vid
    ):
        expected_url = (
            f"https://www.youtube.com/watch?v={vid}"
            f"&t={seconds}s"
        )

        if chunk.get("timestamp_url") != expected_url:
            errors.append({
                **prefix,
                "message": (
                    "timestamp_url does not match "
                    "video_id/timestamp_seconds"
                ),
            })

    start_snippet = chunk.get("source_snippet_start")
    end_snippet = chunk.get("source_snippet_end")

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

    end_seconds = chunk.get("end_seconds")

    if (
        isinstance(seconds, int)
        and isinstance(end_seconds, (int, float))
        and end_seconds < seconds
    ):
        errors.append({
            **prefix,
            "message": "end_seconds precedes timestamp_seconds",
        })

    return errors


def validate_youtube_semantics(
    rows: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    errors = []
    master_chunks: dict[str, dict[str, Any]] = {}

    for row in rows:
        line = row["_validation_line"]
        rid = row.get("id")
        vid = row.get("video_id")
        chunks = row.get("transcript_chunks") or []

        if rid != f"youtube:{vid}":
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    "id must equal 'youtube:' + video_id"
                ),
            })

        expected_words = word_count(
            row.get("full_transcript") or ""
        )

        if (
            row.get("full_transcript_word_count")
            != expected_words
        ):
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    "full_transcript_word_count mismatch: "
                    f"{row.get('full_transcript_word_count')} "
                    f"!= {expected_words}"
                ),
            })

        if row.get("chunk_count") != len(chunks):
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    f"chunk_count mismatch: "
                    f"{row.get('chunk_count')} != {len(chunks)}"
                ),
            })

        expected_indexes = list(range(len(chunks)))
        actual_indexes = [
            chunk.get("chunk_index")
            for chunk in chunks
        ]

        if actual_indexes != expected_indexes:
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    "transcript chunk indexes are not contiguous "
                    "starting at zero"
                ),
            })

        previous_start = -1
        previous_end = -1

        for chunk in chunks:
            errors.extend(
                validate_chunk_semantics(
                    chunk,
                    line=line,
                )
            )

            chunk_id = chunk.get("id")

            if chunk_id in master_chunks:
                errors.append({
                    "line": line,
                    "id": chunk_id,
                    "message": (
                        "duplicate nested YouTube chunk id"
                    ),
                })
            else:
                master_chunks[chunk_id] = chunk_base(chunk)

            start = chunk.get("source_snippet_start")
            end = chunk.get("source_snippet_end")

            if isinstance(start, int):
                if start < previous_start:
                    errors.append({
                        "line": line,
                        "id": chunk_id,
                        "message": (
                            "source snippet order moved backwards"
                        ),
                    })

                # Boundaries may skip empty source caption rows, so
                # monotonicity is the invariant; literal adjacency is not.
                previous_start = start

            if isinstance(end, int):
                previous_end = max(previous_end, end)

        forbidden_master_flags = {
            "contains_oversize_chunk",
        }

        flags = set(row.get("qc_flags") or [])

        bad = sorted(
            forbidden_master_flags & flags
        )

        if bad:
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    "obsolete/forbidden master flags present: "
                    + ", ".join(bad)
                ),
            })

    return errors, master_chunks


def validate_flat_chunks(
    rows: list[dict[str, Any]],
    master_chunks: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    errors = []

    for row in rows:
        line = row["_validation_line"]
        rid = row.get("id")

        errors.extend(
            validate_chunk_semantics(
                row,
                line=line,
            )
        )

        expected = master_chunks.get(rid)

        if expected is None:
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    "flat chunk does not exist in youtube-master-v1"
                ),
            })
            continue

        actual = chunk_base(row)

        if actual != expected:
            errors.append({
                "line": line,
                "id": rid,
                "message": (
                    "flat chunk base fields differ from the "
                    "nested canonical chunk in youtube-master-v1"
                ),
            })

    flat_ids = {
        row.get("id")
        for row in rows
    }

    missing_flat = sorted(
        set(master_chunks) - flat_ids
    )

    for rid in missing_flat:
        errors.append({
            "line": None,
            "id": rid,
            "message": (
                "nested canonical chunk is missing from "
                "youtube-chunks-v1.jsonl"
            ),
        })

    return errors


# ============================================================================
# Report helpers
# ============================================================================

def validation_report(
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
# CLI / main
# ============================================================================

def parse_args():
    parser = ArgumentParser()

    parser.add_argument(
        "--site-root",
        type=Path,
        default=SITE_ROOT_DEFAULT,
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.site_root

    corpus = root / "src" / "site" / "data" / "corpus"
    schemas = root / "config" / "schemas"
    reports = root / "reports" / "migration"

    substack_path = corpus / "substack-master-v1.jsonl"
    youtube_path = corpus / "youtube-master-v1.jsonl"
    chunk_path = corpus / "youtube-chunks-v1.jsonl"

    required = [
        substack_path,
        youtube_path,
        chunk_path,
    ]

    for path in required:
        if not path.exists():
            raise RuntimeError(
                f"Missing canonical input: {path}"
            )

    schema_paths = {
        "substack":
            schemas / "substack-v1.schema.json",
        "youtube":
            schemas / "youtube-v1.schema.json",
        "youtube_chunk":
            schemas / "youtube-chunk-v1.schema.json",
    }

    write_json(
        schema_paths["substack"],
        SUBSTACK_SCHEMA,
    )

    write_json(
        schema_paths["youtube"],
        YOUTUBE_SCHEMA,
    )

    write_json(
        schema_paths["youtube_chunk"],
        YOUTUBE_CHUNK_SCHEMA,
    )

    substack_rows = load_jsonl(substack_path)
    youtube_rows = load_jsonl(youtube_path)
    chunk_rows = load_jsonl(chunk_path)

    substack_schema_errors = schema_errors(
        substack_rows,
        SUBSTACK_SCHEMA,
    )

    youtube_schema_errors = schema_errors(
        youtube_rows,
        YOUTUBE_SCHEMA,
    )

    chunk_schema_errors = schema_errors(
        chunk_rows,
        YOUTUBE_CHUNK_SCHEMA,
    )

    substack_semantic_errors = (
        unique_id_errors(substack_rows)
        + validate_substack_semantics(
            substack_rows
        )
    )

    youtube_unique_errors = unique_id_errors(
        youtube_rows
    )

    youtube_semantic_errors, master_chunks = (
        validate_youtube_semantics(
            youtube_rows
        )
    )

    youtube_semantic_errors = (
        youtube_unique_errors
        + youtube_semantic_errors
    )

    chunk_semantic_errors = (
        unique_id_errors(chunk_rows)
        + validate_flat_chunks(
            chunk_rows,
            master_chunks,
        )
    )

    substack_report = validation_report(
        schema_name="substack-v1.schema.json",
        data_path=substack_path,
        rows=substack_rows,
        schema_errs=substack_schema_errors,
        semantic_errs=substack_semantic_errors,
    )

    youtube_report = validation_report(
        schema_name="youtube-v1.schema.json",
        data_path=youtube_path,
        rows=youtube_rows,
        schema_errs=youtube_schema_errors,
        semantic_errs=youtube_semantic_errors,
    )

    chunk_report = validation_report(
        schema_name="youtube-chunk-v1.schema.json",
        data_path=chunk_path,
        rows=chunk_rows,
        schema_errs=chunk_schema_errors,
        semantic_errs=chunk_semantic_errors,
    )

    report_paths = {
        "substack":
            reports / "substack-v1-validation.json",
        "youtube":
            reports / "youtube-v1-validation.json",
        "youtube_chunk":
            reports / "youtube-chunk-v1-validation.json",
    }

    write_json(
        report_paths["substack"],
        substack_report,
    )

    write_json(
        report_paths["youtube"],
        youtube_report,
    )

    write_json(
        report_paths["youtube_chunk"],
        chunk_report,
    )

    all_reports = [
        substack_report,
        youtube_report,
        chunk_report,
    ]

    total_errors = sum(
        report["validation_errors"]
        for report in all_reports
    )

    print()
    print("======================================")
    print("CANONICAL CORPUS VALIDATION")
    print("======================================")
    print(
        f"Substack records:       {len(substack_rows):,}"
    )
    print(
        f"YouTube records:        {len(youtube_rows):,}"
    )
    print(
        f"YouTube chunks:         {len(chunk_rows):,}"
    )
    print()
    print(
        f"Substack errors:        "
        f"{substack_report['validation_errors']:,}"
    )
    print(
        f"YouTube errors:         "
        f"{youtube_report['validation_errors']:,}"
    )
    print(
        f"YouTube chunk errors:   "
        f"{chunk_report['validation_errors']:,}"
    )
    print()

    if total_errors:
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
        print("CANONICAL VALIDATION FAILED", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        raise
