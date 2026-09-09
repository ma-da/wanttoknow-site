"""WantToKnow.info browser search API.

Drop-in FastAPI router for the phase-1 SQLite + FTS5 search database.

Public endpoints
----------------
POST /api/search
GET  /api/search/options
GET  /api/search/result/{ref_id}
GET  /api/search/related/{ref_id}

The browser never opens SQLite directly. BM25 weights are validated request
parameters and are bound into SQLite's bm25() expression. Searchable plain
text stays separate from display_markdown; detail responses render that stored
Markdown to HTML at the API boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Literal
import json
import logging
import os
import re
import sqlite3

import markdown
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["search"])

TOKEN_RE = re.compile(r"[^\s]+")
HIGHLIGHT_START = "\uE000"
HIGHLIGHT_END = "\uE001"

Family = Literal["news", "document", "youtube"]
RecordType = Literal[
    "news",
    "page_chunk",
    "substack_chunk",
    "youtube_chunk",
]

# Keep these defaults synchronized with DEFAULT_WEIGHTS in search.js.
DEFAULT_SEARCH_WEIGHTS = {
    "title": 3.0,
    "text": 6.0,
    "publisher": 2.0,
    "topics": 2.5,
}


class SearchWeights(BaseModel):
    title: float = Field(default=DEFAULT_SEARCH_WEIGHTS["title"], ge=0.0, le=20.0)
    text: float = Field(default=DEFAULT_SEARCH_WEIGHTS["text"], ge=0.0, le=20.0)
    publisher: float = Field(default=DEFAULT_SEARCH_WEIGHTS["publisher"], ge=0.0, le=20.0)
    topics: float = Field(default=DEFAULT_SEARCH_WEIGHTS["topics"], ge=0.0, le=20.0)


class SearchFilters(BaseModel):
    families: list[Family] = Field(default_factory=list)
    record_types: list[RecordType] = Field(default_factory=list)
    publishers: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    inspiring_only: bool = False


class SearchRequest(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    weights: SearchWeights = Field(default_factory=SearchWeights)
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=100_000)


class SearchResult(BaseModel):
    rank: int
    ref_id: int
    family: Family
    record_type: RecordType
    title: str
    url: str
    published_at: str | None = None
    publisher: str | None = None
    section: str | None = None
    topic: str | None = None
    priority: float | None = None
    score: float
    snippet: str | None = None
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = None
    video_id: str | None = None
    timestamp_seconds: float | None = None


class SearchDetail(BaseModel):
    ref_id: int
    family: Family
    record_type: RecordType
    title: str
    url: str
    published_at: str | None = None
    publisher: str | None = None
    section: str | None = None
    topic: str | None = None
    text: str
    display_markdown: str = ""
    display_html: str = ""


class SearchRecord(BaseModel):
    ref_id: int
    family: Family
    record_type: RecordType
    title: str
    url: str
    published_at: str | None = None
    publisher: str | None = None
    video_id: str | None = None
    timestamp_seconds: float | None = None


class SearchRelatedResponse(BaseModel):
    target: SearchRecord
    related: list[SearchRecord]


class QueryReplacement(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = {
        "populate_by_name": True,
    }


class SearchResponse(BaseModel):
    query: str
    canonical_query: str
    normalized_query: str

    query_replacements: list[QueryReplacement] = Field(
        default_factory=list
    )

    query_mode: Literal[
        "all_terms",
        "normalized",
    ] = "all_terms"

    score_order: Literal["ascending"] = "ascending"

    total: int
    offset: int
    limit: int
    has_more: bool

    weights: SearchWeights
    filters: SearchFilters
    results: list[SearchResult]


@dataclass(frozen=True)
class SearchSourceRecord:
    """Stored source text and metadata for a small ordered set of search refs."""

    ref_id: int
    family: Family
    record_type: RecordType
    title: str
    url: str
    published_at: str | None
    publisher: str | None
    section: str | None
    topic: str | None
    text: str
    source_url: str | None


_OPTIONS_CACHE: dict[str, object] = {
    "signature": None,
    "payload": None,
}
_OPTIONS_LOCK = Lock()

_RELATED_MAP_CACHE: dict[str, object] = {
    "signature": None,
    "payload": None,
}
_RELATED_MAP_LOCK = Lock()

_ENTITY_QUERY_MAP_CACHE: dict[str, object] = {
    "signature": None,
    "mapping": None,
    "trie": None,
}

_ENTITY_QUERY_MAP_LOCK = Lock()

QUERY_NORMALIZE_WS_RE = re.compile(r"\s+")


def _normalize_entity_key(value: str) -> str:
    """
    Normalize text into the same form used for entity-map lookup.

    The source map is assumed to contain lowercase, whitespace-normalized
    lookup keys such as:

        "mk ultra"
        "john f kennedy"
        "1017 18 5th cir"
    """
    return QUERY_NORMALIZE_WS_RE.sub(
        " ",
        str(value or "").strip().casefold(),
    )


def _build_entity_query_trie(
    mapping: dict[str, str],
) -> dict:
    """
    Build a token trie so multi-word aliases can be matched efficiently
    without constructing an enormous regular expression.
    """
    root: dict = {}

    for raw_key, raw_value in mapping.items():
        key = _normalize_entity_key(raw_key)
        value = _normalize_entity_key(raw_value)

        if not key or not value:
            continue

        tokens = key.split()

        node = root

        for token in tokens:
            node = node.setdefault(token, {})

        node["__value__"] = value

    return root
    
def _load_entity_query_map() -> tuple[dict[str, str], dict]:
    path = _entity_query_map_path()

    if not path.is_file():
        logger.warning(
            "Entity query normalization map not found: %s",
            path,
        )
        return {}, {}

    stat = path.stat()

    signature = (
        stat.st_mtime_ns,
        stat.st_size,
    )

    with _ENTITY_QUERY_MAP_LOCK:
        if (
            _ENTITY_QUERY_MAP_CACHE["signature"]
            == signature
            and isinstance(
                _ENTITY_QUERY_MAP_CACHE["mapping"],
                dict,
            )
            and isinstance(
                _ENTITY_QUERY_MAP_CACHE["trie"],
                dict,
            )
        ):
            return (
                _ENTITY_QUERY_MAP_CACHE["mapping"],
                _ENTITY_QUERY_MAP_CACHE["trie"],
            )

        payload = json.loads(
            path.read_text(encoding="utf-8")
        )

        if not isinstance(payload, dict):
            raise ValueError(
                "Entity query normalization map must be a JSON object."
            )

        mapping: dict[str, str] = {}

        for raw_key, raw_value in payload.items():
            key = _normalize_entity_key(raw_key)
            value = _normalize_entity_key(raw_value)

            if key and value:
                mapping[key] = value

        trie = _build_entity_query_trie(mapping)

        _ENTITY_QUERY_MAP_CACHE["signature"] = signature
        _ENTITY_QUERY_MAP_CACHE["mapping"] = mapping
        _ENTITY_QUERY_MAP_CACHE["trie"] = trie

        logger.info(
            "Loaded %s entity query normalizations from %s",
            f"{len(mapping):,}",
            path,
        )

        return mapping, trie

def _fts_term(token: str) -> str:
    return (
        '"'
        + str(token).replace('"', '""')
        + '"'
    )


def _fts_and_phrase(tokens: list[str]) -> str:
    return " AND ".join(
        _fts_term(token)
        for token in tokens
        if token
    )


def build_entity_aware_fts_query(
    query: str,
) -> tuple[str, list[dict[str, str]]]:
    """
    Build an FTS5 expression that preserves the user's original terms
    while adding known canonical equivalents from the entity map.

    Examples:

        goverment
        ->
        ("goverment" OR "government")

        mk ultra experiments
        ->
        (("mk" AND "ultra") OR "mkultra")
        AND "experiments"
    """

    original = QUERY_NORMALIZE_WS_RE.sub(
        " ",
        str(query or "").strip(),
    )

    if not original:
        return "", []

    _, trie = _load_entity_query_map()

    lookup_query = _normalize_entity_key(
        original
    )

    tokens = lookup_query.split()

    if not tokens:
        return "", []

    output_groups: list[str] = []
    replacements: list[dict[str, str]] = []

    index = 0

    while index < len(tokens):
        node = trie
        cursor = index

        best_end: int | None = None
        best_value: str | None = None

        # Longest matching map key wins.
        while cursor < len(tokens):
            token = tokens[cursor]

            child = node.get(token)

            if not isinstance(child, dict):
                break

            node = child

            canonical = node.get("__value__")

            if isinstance(canonical, str):
                best_end = cursor + 1
                best_value = canonical

            cursor += 1

        if (
            best_end is not None
            and best_value is not None
        ):
            original_tokens = tokens[
                index:best_end
            ]

            original_text = " ".join(
                original_tokens
            )

            canonical_tokens = (
                best_value.split()
            )

            # Identity mappings need no expansion.
            if best_value == original_text:
                output_groups.append(
                    _fts_and_phrase(
                        original_tokens
                    )
                )

            else:
                original_fts = (
                    _fts_and_phrase(
                        original_tokens
                    )
                )

                canonical_fts = (
                    _fts_and_phrase(
                        canonical_tokens
                    )
                )

                output_groups.append(
                    f"(({original_fts}) "
                    f"OR ({canonical_fts}))"
                )

                replacements.append(
                    {
                        "from": original_text,
                        "to": best_value,
                    }
                )

            index = best_end
            continue

        # No map entry: preserve normal search behavior.
        output_groups.append(
            _fts_term(tokens[index])
        )

        index += 1

    return (
        " AND ".join(output_groups),
        replacements,
    )       


def _repo_root() -> Path:
    # Expected location: <repo>/backend/app/search_router.py
    return Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    override = os.environ.get("WTK_SEARCH_DB", "").strip()

    if override:
        return Path(override).expanduser()

    return (
        _repo_root()
        / "src"
        / "site"
        / "data"
        / "search"
        / "wanttoknow-search.sqlite"
    )

def _entity_query_map_path() -> Path:
    override = os.environ.get(
        "WTK_ENTITY_QUERY_MAP",
        "",
    ).strip()

    if override:
        return Path(override).expanduser()

    return (
        _repo_root()
        / "src"
        / "site"
        / "data"
        / "entity_query_normalization_map.flat.json"
    )

def _related_map_path() -> Path:
    override = os.environ.get("WTK_RELATED_MAP", "").strip()

    if override:
        return Path(override).expanduser()

    return (
        _repo_root()
        / "src"
        / "site"
        / "data"
        / "search"
        / "related-content.json"
    )


def _load_related_map() -> dict[str, list[int]]:
    path = _related_map_path()

    if not path.is_file():
        raise FileNotFoundError(f"Related map not found: {path}")

    stat = path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)

    with _RELATED_MAP_LOCK:
        if (
            _RELATED_MAP_CACHE["signature"] == signature
            and isinstance(_RELATED_MAP_CACHE["payload"], dict)
        ):
            return _RELATED_MAP_CACHE["payload"]

        payload = json.loads(path.read_text(encoding="utf-8"))

        if not isinstance(payload, dict):
            raise ValueError("Related map must be a JSON object.")

        normalized: dict[str, list[int]] = {}

        for key, values in payload.items():
            if not isinstance(values, list):
                continue

            refs: list[int] = []

            for value in values:
                try:
                    ref_id = int(value)
                except (TypeError, ValueError):
                    continue

                if ref_id > 0:
                    refs.append(ref_id)

            normalized[str(key)] = refs

        _RELATED_MAP_CACHE["signature"] = signature
        _RELATED_MAP_CACHE["payload"] = normalized
        return normalized


def _connect_readonly() -> sqlite3.Connection:
    path = _db_path()

    if not path.is_file():
        raise FileNotFoundError(f"Search database not found: {path}")

    connection = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA temp_store = MEMORY")
    return connection


def safe_fts_query(text: str) -> str:
    """Match the existing CLI behavior: quoted whitespace tokens joined by AND."""
    tokens = [
        token.strip()
        for token in TOKEN_RE.findall(text)
        if token.strip()
    ]

    return " AND ".join(
        '"' + token.replace('"', '""') + '"'
        for token in tokens
    )


def _clean_exact_values(
    values: list[str],
    *,
    field_name: str,
    max_items: int = 20,
    max_length: int = 200,
) -> list[str]:
    if len(values) > max_items:
        raise ValueError(f"Too many {field_name} filters; maximum is {max_items}.")

    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = str(value).strip()

        if not text:
            continue

        if len(text) > max_length:
            raise ValueError(
                f"{field_name} filter values may not exceed {max_length} characters."
            )

        marker = text.casefold()
        if marker in seen:
            continue

        seen.add(marker)
        output.append(text)

    return output


def _in_filter(
    where: list[str],
    params: list[object],
    column: str,
    values: list[str],
) -> None:
    if not values:
        return

    placeholders = ", ".join("?" for _ in values)
    where.append(f"{column} IN ({placeholders})")
    params.extend(values)

def _fts_term(value: str) -> str:
    """
    Safely quote one FTS5 term.
    """
    return '"' + str(value).replace('"', '""') + '"'


def _fts_and_terms(tokens: list[str]) -> str:
    """
    Preserve the site's normal all-terms search semantics.
    """
    return " AND ".join(
        _fts_term(token)
        for token in tokens
        if token
    )


def build_entity_aware_fts_query(
    query: str,
) -> tuple[str, list[dict[str, str]]]:
    """
    Build an FTS5 query that preserves the user's original wording while
    adding known canonical alternatives from the entity normalization map.

    Examples:

        goverment
        ->
        ("goverment" OR "government")

        mk ultra experiments
        ->
        (("mk" AND "ultra") OR "mkultra") AND "experiments"

        1000 bc history
        ->
        (("1000" AND "bc") OR "1000") AND "history"

    Longest matching entity-map key wins.
    """

    original = QUERY_NORMALIZE_WS_RE.sub(
        " ",
        str(query or "").strip(),
    )

    if not original:
        return "", []

    _, trie = _load_entity_query_map()

    # If the map is unavailable, preserve the site's original behavior.
    if not trie:
        return safe_fts_query(original), []

    lookup_query = _normalize_entity_key(original)
    tokens = lookup_query.split()

    if not tokens:
        return "", []

    groups: list[str] = []
    replacements: list[dict[str, str]] = []

    index = 0

    while index < len(tokens):
        node = trie
        cursor = index

        best_end: int | None = None
        best_value: str | None = None

        # Find the longest mapped phrase beginning at this token.
        while cursor < len(tokens):
            token = tokens[cursor]
            child = node.get(token)

            if not isinstance(child, dict):
                break

            node = child

            canonical = node.get("__value__")

            if isinstance(canonical, str) and canonical.strip():
                best_end = cursor + 1
                best_value = canonical.strip()

            cursor += 1

        if best_end is None or best_value is None:
            # No normalization exists here. This is exactly the behavior
            # the old search used for this token.
            groups.append(
                _fts_term(tokens[index])
            )
            index += 1
            continue

        original_tokens = tokens[index:best_end]
        original_text = " ".join(original_tokens)

        canonical_text = _normalize_entity_key(best_value)
        canonical_tokens = canonical_text.split()

        original_fts = _fts_and_terms(original_tokens)

        # Identity mappings such as "1014" -> "1014" do not need OR expansion.
        if canonical_text == original_text:
            groups.append(original_fts)
            index = best_end
            continue

        canonical_fts = _fts_and_terms(canonical_tokens)

        # Preserve original matching AND allow the known canonical equivalent.
        groups.append(
            f"(({original_fts}) OR ({canonical_fts}))"
        )

        replacements.append(
            {
                "from": original_text,
                "to": canonical_text,
            }
        )

        index = best_end

    return " AND ".join(groups), replacements

def _search_sync(request: SearchRequest) -> SearchResponse:
    query_text = request.q.strip()

    normalized_query, query_replacements = (
        build_entity_aware_fts_query(
            query_text
        )
    )

    if not normalized_query:
        raise ValueError(
            "Query contains no searchable terms."
        )

    # Informational only. The executed FTS query is normalized_query.
    canonical_query = query_text

    if query_replacements:
        canonical_query = query_text.casefold()

        for replacement in query_replacements:
            original = str(
                replacement.get("from") or ""
            ).strip()

            canonical = str(
                replacement.get("to") or ""
            ).strip()

            if original and canonical:
                canonical_query = canonical_query.replace(
                    original.casefold(),
                    canonical,
                )

    publishers = _clean_exact_values(
        request.filters.publishers,
        field_name="publisher",
    )
    terms = _clean_exact_values(
        request.filters.terms,
        field_name="topic/category",
    )

    clean_filters = SearchFilters(
        families=list(dict.fromkeys(request.filters.families)),
        record_types=list(dict.fromkeys(request.filters.record_types)),
        publishers=publishers,
        terms=terms,
        inspiring_only=bool(request.filters.inspiring_only),
    )

    where = ["fts_content MATCH ?"]
    where_params: list[object] = [normalized_query]

    _in_filter(where, where_params, "c.family", clean_filters.families)
    _in_filter(where, where_params, "c.record_type", clean_filters.record_types)
    _in_filter(where, where_params, "c.publisher", clean_filters.publishers)

    # Multiple selected topic/category terms use AND semantics. Each exact term
    # may be stored as a normalized topic or tag; playlists and sections remain
    # available in content_terms for future filters but are not mixed into this UI.
    for term in clean_filters.terms:
        where.append(
            """
            EXISTS (
                SELECT 1
                FROM content_terms AS ct
                WHERE ct.ref_id = c.ref_id
                  AND ct.kind IN ('topic', 'tag')
                  AND ct.value = ? COLLATE NOCASE
            )
            """
        )
        where_params.append(term)

    if clean_filters.inspiring_only:
        where.append(
            """
            (
                (
                    c.record_type = 'news'
                    AND EXISTS (
                        SELECT 1
                        FROM content_terms AS inspiring_term
                        WHERE inspiring_term.ref_id = c.ref_id
                          AND inspiring_term.kind = 'tag'
                          AND lower(inspiring_term.value) IN (
                              'inspiring',
                              'inspirational'
                          )
                    )
                )
                OR
                (
                    c.record_type = 'page_chunk'
                    AND (
                        lower(c.url) IN (
                            '/inspiring',
                            '/inspiring/'
                        )
                        OR lower(c.url) LIKE '/inspiring/%'
                        OR lower(c.url) LIKE 'https://www.wanttoknow.info/inspiring/%'
                        OR lower(c.url) LIKE 'https://wanttoknow.info/inspiring/%'
                        OR lower(c.url) LIKE 'http://www.wanttoknow.info/inspiring/%'
                        OR lower(c.url) LIKE 'http://wanttoknow.info/inspiring/%'
                        OR lower(c.url) IN (
                            'https://www.wanttoknow.info/inspiring',
                            'https://www.wanttoknow.info/inspiring/',
                            'https://wanttoknow.info/inspiring',
                            'https://wanttoknow.info/inspiring/',
                            'http://www.wanttoknow.info/inspiring',
                            'http://www.wanttoknow.info/inspiring/',
                            'http://wanttoknow.info/inspiring',
                            'http://wanttoknow.info/inspiring/'
                        )
                    )
                )
            )
            """
        )

    where_sql = " AND ".join(where)

    count_sql = f"""
        SELECT COUNT(*)
        FROM fts_content
        JOIN content AS c
          ON c.ref_id = fts_content.rowid
        WHERE {where_sql}
    """

    results_sql = f"""
        SELECT
            c.ref_id,
            c.family,
            c.record_type,
            c.title,
            c.url,
            c.published_at,
            c.publisher,
            c.section,
            c.topic,
            c.priority,
            c.metadata_json,
            bm25(
                fts_content,
                ?,  -- title
                ?,  -- text
                ?,  -- publisher
                ?   -- topics
            ) AS score,
            snippet(
                fts_content,
                1,
                '{HIGHLIGHT_START}',
                '{HIGHLIGHT_END}',
                ' … ',
                32
            ) AS snippet
        FROM fts_content
        JOIN content AS c
          ON c.ref_id = fts_content.rowid
        WHERE {where_sql}
        ORDER BY
            score ASC,
            COALESCE(c.priority, 0) DESC,
            c.ref_id ASC
        LIMIT ? OFFSET ?
    """

    weights = request.weights
    result_params: list[object] = [
        weights.title,
        weights.text,
        weights.publisher,
        weights.topics,
        *where_params,
        request.limit,
        request.offset,
    ]

    connection = _connect_readonly()
    tags_by_ref: dict[int, list[str]] = {}

    try:
        total = int(
            connection.execute(count_sql, where_params).fetchone()[0]
        )
        rows = connection.execute(results_sql, result_params).fetchall()

        news_ref_ids = [
            int(row["ref_id"])
            for row in rows
            if row["record_type"] == "news"
        ]

        if news_ref_ids:
            placeholders = ", ".join("?" for _ in news_ref_ids)
            tag_rows = connection.execute(
                f"""
                SELECT
                    ref_id,
                    value
                FROM content_terms
                WHERE kind = 'tag'
                  AND ref_id IN ({placeholders})
                ORDER BY
                    ref_id ASC,
                    value COLLATE NOCASE ASC
                """,
                news_ref_ids,
            ).fetchall()

            for tag_row in tag_rows:
                ref_id = int(tag_row["ref_id"])
                tags_by_ref.setdefault(ref_id, []).append(tag_row["value"])
    finally:
        connection.close()

    results: list[SearchResult] = []

    for index, row in enumerate(rows):
        metadata = _decode_metadata(row["metadata_json"])
        record_type = row["record_type"]

        source_url = None
        video_id = None
        timestamp_seconds = None

        if record_type == "news":
            raw_source_url = str(metadata.get("source_url") or "").strip()
            source_url = raw_source_url or None

        if record_type == "youtube_chunk":
            raw_video_id = str(metadata.get("video_id") or "").strip()
            video_id = raw_video_id or None
            timestamp_seconds = _optional_float(
                metadata.get("timestamp_seconds")
            )

        results.append(
            SearchResult(
                rank=request.offset + index + 1,
                ref_id=int(row["ref_id"]),
                family=row["family"],
                record_type=record_type,
                title=row["title"] or "",
                url=row["url"] or "",
                published_at=row["published_at"],
                publisher=row["publisher"],
                section=row["section"],
                topic=row["topic"],
                priority=(
                    float(row["priority"])
                    if row["priority"] is not None
                    else None
                ),
                score=float(row["score"]),
                snippet=row["snippet"],
                tags=tags_by_ref.get(int(row["ref_id"]), []),
                source_url=source_url,
                video_id=video_id,
                timestamp_seconds=timestamp_seconds,
            )
        )

    return SearchResponse(
        query=query_text,
        canonical_query=canonical_query,
        normalized_query=normalized_query,
        query_replacements=query_replacements,
        query_mode=(
            "normalized"
            if query_replacements
            else "all_terms"
        ),
        total=total,
        offset=request.offset,
        limit=request.limit,
        has_more=(
            request.offset + len(results)
        ) < total,
        weights=request.weights,
        filters=clean_filters,
        results=results,
    )


def _decode_metadata(value: str | None) -> dict[str, object]:
    """Decode family-specific metadata without exposing metadata_json directly."""
    if not value:
        return {}

    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}

    return data if isinstance(data, dict) else {}


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _render_display_markdown(value: str) -> str:
    """Render stored presentation Markdown at the API boundary."""
    source = str(value or "").strip()

    if not source:
        return ""

    return markdown.markdown(
        source,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )


def _detail_sync(ref_id: int) -> SearchDetail | None:
    connection = _connect_readonly()

    try:
        row = connection.execute(
            """
            SELECT
                ref_id,
                family,
                record_type,
                title,
                url,
                published_at,
                publisher,
                section,
                topic,
                text,
                display_markdown
            FROM content
            WHERE ref_id = ?
            """,
            (ref_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return None

    return SearchDetail(
        ref_id=int(row["ref_id"]),
        family=row["family"],
        record_type=row["record_type"],
        title=row["title"] or "",
        url=row["url"] or "",
        published_at=row["published_at"],
        publisher=row["publisher"],
        section=row["section"],
        topic=row["topic"],
        text=row["text"] or "",
        display_markdown=row["display_markdown"] or "",
        display_html=_render_display_markdown(
            row["display_markdown"] or ""
        ),
    )


def _source_records_sync(ref_ids: list[int]) -> list[SearchSourceRecord]:
    """Resolve stored content.text for a small ordered set of ranked refs."""
    normalized: list[int] = []
    seen: set[int] = set()

    for value in ref_ids:
        ref_id = int(value)

        if ref_id < 1 or ref_id in seen:
            continue

        seen.add(ref_id)
        normalized.append(ref_id)

    if not normalized:
        return []

    placeholders = ", ".join("?" for _ in normalized)
    connection = _connect_readonly()

    try:
        rows = connection.execute(
            f"""
            SELECT
                ref_id,
                family,
                record_type,
                title,
                url,
                published_at,
                publisher,
                section,
                topic,
                text,
                metadata_json
            FROM content
            WHERE ref_id IN ({placeholders})
            """,
            normalized,
        ).fetchall()
    finally:
        connection.close()

    by_ref: dict[int, SearchSourceRecord] = {}

    for row in rows:
        metadata = _decode_metadata(row["metadata_json"])
        source_url = None

        if row["record_type"] == "news":
            raw_source_url = str(metadata.get("source_url") or "").strip()
            source_url = raw_source_url or None

        record = SearchSourceRecord(
            ref_id=int(row["ref_id"]),
            family=row["family"],
            record_type=row["record_type"],
            title=row["title"] or "",
            url=row["url"] or "",
            published_at=row["published_at"],
            publisher=row["publisher"],
            section=row["section"],
            topic=row["topic"],
            text=row["text"] or "",
            source_url=source_url,
        )
        by_ref[record.ref_id] = record

    return [
        by_ref[ref_id]
        for ref_id in normalized
        if ref_id in by_ref
    ]


def _records_sync(ref_ids: list[int]) -> list[SearchRecord]:
    """Resolve a small ordered set of refs for related-content visualization."""
    normalized: list[int] = []
    seen: set[int] = set()

    for value in ref_ids:
        ref_id = int(value)

        if ref_id < 1 or ref_id in seen:
            continue

        seen.add(ref_id)
        normalized.append(ref_id)

    if not normalized:
        return []

    placeholders = ", ".join("?" for _ in normalized)
    connection = _connect_readonly()

    try:
        rows = connection.execute(
            f"""
            SELECT
                ref_id,
                family,
                record_type,
                title,
                url,
                published_at,
                publisher,
                metadata_json
            FROM content
            WHERE ref_id IN ({placeholders})
            """,
            normalized,
        ).fetchall()
    finally:
        connection.close()

    by_ref: dict[int, SearchRecord] = {}

    for row in rows:
        metadata = _decode_metadata(row["metadata_json"])
        video_id = None
        timestamp_seconds = None

        if row["record_type"] == "youtube_chunk":
            raw_video_id = str(metadata.get("video_id") or "").strip()
            video_id = raw_video_id or None
            timestamp_seconds = _optional_float(
                metadata.get("timestamp_seconds")
            )

        record = SearchRecord(
            ref_id=int(row["ref_id"]),
            family=row["family"],
            record_type=row["record_type"],
            title=row["title"] or "",
            url=row["url"] or "",
            published_at=row["published_at"],
            publisher=row["publisher"],
            video_id=video_id,
            timestamp_seconds=timestamp_seconds,
        )
        by_ref[record.ref_id] = record

    return [
        by_ref[ref_id]
        for ref_id in normalized
        if ref_id in by_ref
    ]


def _related_sync(ref_id: int) -> SearchRelatedResponse | None:
    related_map = _load_related_map()
    related_ids = related_map.get(str(ref_id), [])[:24]

    records = _records_sync([
        ref_id,
        *related_ids,
    ])

    by_ref = {
        record.ref_id: record
        for record in records
    }

    target = by_ref.get(ref_id)

    if target is None:
        return None

    return SearchRelatedResponse(
        target=target,
        related=[
            by_ref[related_id]
            for related_id in related_ids
            if related_id in by_ref
        ],
    )


def _option_rows(
    connection: sqlite3.Connection,
    sql: str,
    params: tuple[object, ...] = (),
) -> list[dict[str, object]]:
    return [
        {
            "value": row["value"],
            "count": int(row["count"]),
        }
        for row in connection.execute(sql, params).fetchall()
    ]


def _options_sync() -> dict[str, object]:
    path = _db_path()

    if not path.is_file():
        raise FileNotFoundError(f"Search database not found: {path}")

    stat = path.stat()
    signature = (stat.st_mtime_ns, stat.st_size)

    with _OPTIONS_LOCK:
        if (
            _OPTIONS_CACHE["signature"] == signature
            and _OPTIONS_CACHE["payload"] is not None
        ):
            return _OPTIONS_CACHE["payload"]  # type: ignore[return-value]

        connection = _connect_readonly()

        try:
            build_meta = {
                row["key"]: row["value"]
                for row in connection.execute(
                    "SELECT key, value FROM build_meta"
                ).fetchall()
            }

            active_refs = int(
                connection.execute("SELECT COUNT(*) FROM content").fetchone()[0]
            )

            families = _option_rows(
                connection,
                """
                SELECT family AS value, COUNT(*) AS count
                FROM content
                GROUP BY family
                ORDER BY count DESC, value ASC
                """,
            )

            record_types = _option_rows(
                connection,
                """
                SELECT record_type AS value, COUNT(*) AS count
                FROM content
                GROUP BY record_type
                ORDER BY count DESC, value ASC
                """,
            )

            publishers = _option_rows(
                connection,
                """
                SELECT MIN(publisher) AS value, COUNT(*) AS count
                FROM content
                WHERE publisher IS NOT NULL
                  AND trim(publisher) <> ''
                GROUP BY publisher COLLATE NOCASE
                ORDER BY count DESC, value COLLATE NOCASE ASC
                """,
            )

            terms = _option_rows(
                connection,
                """
                SELECT MIN(value) AS value, COUNT(DISTINCT ref_id) AS count
                FROM content_terms
                WHERE kind IN ('topic', 'tag')
                  AND trim(value) <> ''
                GROUP BY value COLLATE NOCASE
                ORDER BY count DESC, value COLLATE NOCASE ASC
                LIMIT 500
                """,
            )
        finally:
            connection.close()

        payload: dict[str, object] = {
            "corpus": {
                "active_refs": active_refs,
                "built_at": build_meta.get("built_at"),
                "schema_version": build_meta.get("schema_version"),
            },
            "families": families,
            "record_types": record_types,
            "publishers": publishers,
            "terms": terms,
            "default_weights": DEFAULT_SEARCH_WEIGHTS,
        }

        _OPTIONS_CACHE["signature"] = signature
        _OPTIONS_CACHE["payload"] = payload
        return payload


@router.post("", response_model=SearchResponse)
async def search(request: SearchRequest, response: Response) -> SearchResponse:
    response.headers["Cache-Control"] = "no-store"

    try:
        return await run_in_threadpool(_search_sync, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        logger.error("Search database unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Search database is unavailable.",
        ) from exc
    except sqlite3.OperationalError as exc:
        logger.exception("SQLite search failed")
        raise HTTPException(
            status_code=500,
            detail="Search could not be completed.",
        ) from exc


@router.get("/options")
async def search_options(response: Response) -> dict[str, object]:
    response.headers["Cache-Control"] = "public, max-age=300"

    try:
        return await run_in_threadpool(_options_sync)
    except FileNotFoundError as exc:
        logger.error("Search database unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Search database is unavailable.",
        ) from exc
    except sqlite3.OperationalError as exc:
        logger.exception("SQLite search options failed")
        raise HTTPException(
            status_code=500,
            detail="Search filter options could not be loaded.",
        ) from exc


@router.get("/related/{ref_id}", response_model=SearchRelatedResponse)
async def search_related(
    ref_id: int,
    response: Response,
) -> SearchRelatedResponse:
    response.headers["Cache-Control"] = "no-store"

    if ref_id < 1:
        raise HTTPException(status_code=404, detail="Search entry not found.")

    try:
        payload = await run_in_threadpool(_related_sync, ref_id)
    except FileNotFoundError as exc:
        logger.error("Related map unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Related articles are unavailable.",
        ) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        logger.exception("Related map could not be decoded")
        raise HTTPException(
            status_code=500,
            detail="Related articles could not be loaded.",
        ) from exc
    except sqlite3.OperationalError as exc:
        logger.exception("SQLite related-record lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Related articles could not be loaded.",
        ) from exc

    if payload is None:
        raise HTTPException(status_code=404, detail="Search entry not found.")

    return payload


@router.get("/result/{ref_id}", response_model=SearchDetail)
async def search_result_detail(ref_id: int, response: Response) -> SearchDetail:
    response.headers["Cache-Control"] = "no-store"

    if ref_id < 1:
        raise HTTPException(status_code=404, detail="Search entry not found.")

    try:
        detail = await run_in_threadpool(_detail_sync, ref_id)
    except FileNotFoundError as exc:
        logger.error("Search database unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Search database is unavailable.",
        ) from exc
    except sqlite3.OperationalError as exc:
        logger.exception("SQLite search detail lookup failed")
        raise HTTPException(
            status_code=500,
            detail="Search entry could not be loaded.",
        ) from exc

    if detail is None:
        raise HTTPException(status_code=404, detail="Search entry not found.")

    return detail
