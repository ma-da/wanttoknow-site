#!/usr/bin/env python3
"""
Build WantToKnow.info derived searchable chunks + persistent universal ref IDs.

Canonical inputs are read-only.

Inputs
------
src/site/data/corpus/pages-v1.jsonl
src/site/data/corpus/substack-master-v1.jsonl
src/site/data/corpus/youtube-chunks-v1.jsonl
src/site/data/article-index.jsonl

Outputs
-------
src/site/data/corpus/document-chunks-v1.jsonl
src/site/data/corpus/youtube-search-chunks-v1.jsonl
src/site/data/corpus/ref-registry-v1.jsonl

Report
------
reports/build/search-corpus-build.json

ref_id namespaces
-----------------
1..99,999       Existing news ArticleIDs (ref_id == article_id)
100,000..999,999
                Page + Substack chunks
1,000,000+      YouTube transcript chunks

Document chunk policy
---------------------
Target: 290 words
Soft minimum: 260 words
HARD maximum: 320 words
No duplicated or discarded words.
"""

from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Iterable
import hashlib
import json
import math
import re
import sys


DEFAULT_SITE_ROOT = Path("/mnt/c/datasources/wanttoknow-site")

DOC_MIN = 260
DOC_TARGET = 290
DOC_MAX = 320

NEWS_MIN = 1
NEWS_MAX = 99_999

DOCUMENT_MIN = 100_000
DOCUMENT_MAX = 999_999

YOUTUBE_MIN = 1_000_000

WORD_RE = re.compile(r"\S+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CODE_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
LIST_RE = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+")
QUOTE_RE = re.compile(r"^\s*>\s?")
HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
REF_LINK_RE = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
HTML_RE = re.compile(r"<[^>]+>")


# ============================================================================
# Generic I/O
# ============================================================================

def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def clean_space(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        "" if value is None else str(value),
    ).strip()


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
                    f"{path}:{line_no}: expected JSON object."
                )

            rows.append(row)

    return rows


def write_jsonl(
    path: Path,
    rows: Iterable[dict[str, Any]],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            f.write("\n")
            count += 1

    return count


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def stable_unique(values: Iterable[Any]) -> list[Any]:
    seen = set()
    output = []

    for value in values:
        marker = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
        )

        if marker in seen:
            continue

        seen.add(marker)
        output.append(value)

    return output


# ============================================================================
# Markdown -> search-word stream
# ============================================================================

def strip_inline_markdown(text: str) -> str:
    text = unescape(text or "")

    text = IMAGE_RE.sub(
        lambda match: match.group(1),
        text,
    )

    text = LINK_RE.sub(
        lambda match: match.group(1),
        text,
    )

    text = REF_LINK_RE.sub(
        lambda match: match.group(1),
        text,
    )

    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = HTML_RE.sub(" ", text)

    for marker in ("**", "__", "~~"):
        text = text.replace(marker, "")

    text = text.replace("*", "")
    text = text.replace("_", "")

    return clean_space(text)


def markdown_blocks(markdown: str) -> list[dict[str, Any]]:
    """
    Convert Markdown to visible-text blocks carrying heading context.

    Heading text is stored as metadata rather than duplicated into the block
    body. Blank lines, list items, and blockquotes become preferred boundaries.
    """
    heading_stack: list[str | None] = [None] * 6
    blocks: list[dict[str, Any]] = []

    paragraph: list[str] = []
    paragraph_heading: tuple[str, ...] = ()
    in_code = False

    def heading_path() -> tuple[str, ...]:
        return tuple(
            heading
            for heading in heading_stack
            if heading
        )

    def flush() -> None:
        if not paragraph:
            return

        text = strip_inline_markdown(
            " ".join(paragraph)
        )

        paragraph.clear()

        if not text:
            return

        blocks.append({
            "text": text,
            "heading_path": paragraph_heading,
        })

    for raw_line in (markdown or "").splitlines():
        line = raw_line.rstrip()

        if CODE_FENCE_RE.match(line):
            flush()
            in_code = not in_code
            continue

        if not in_code:
            heading_match = HEADING_RE.match(line)

            if heading_match:
                flush()

                level = len(heading_match.group(1))
                heading = strip_inline_markdown(
                    heading_match.group(2)
                )

                heading_stack[level - 1] = heading or None

                for index in range(level, 6):
                    heading_stack[index] = None

                continue

            if HR_RE.match(line):
                flush()
                continue

        if not line.strip():
            flush()
            continue

        cleaned = line

        if not in_code:
            cleaned = QUOTE_RE.sub("", cleaned)

            if LIST_RE.match(cleaned):
                # Treat list items as their own semantic blocks.
                flush()
                paragraph_heading = heading_path()
                cleaned = LIST_RE.sub("", cleaned)
                paragraph.append(cleaned)
                flush()
                continue

        if not paragraph:
            paragraph_heading = heading_path()

        paragraph.append(cleaned)

    flush()

    return blocks


def markdown_word_stream(markdown: str) -> list[dict[str, Any]]:
    stream: list[dict[str, Any]] = []

    for block_index, block in enumerate(markdown_blocks(markdown)):
        tokens = WORD_RE.findall(block["text"])

        for token in tokens:
            stream.append({
                "word": token,
                "heading_path": block["heading_path"],
                "block_index": block_index,
                "break_after": False,
            })

        if tokens:
            stream[-1]["break_after"] = True

    return stream


# ============================================================================
# Strict document chunking
# ============================================================================

def balanced_sizes(total_words: int) -> list[int]:
    """
    Balance chunks around DOC_TARGET while enforcing DOC_MAX as a hard ceiling.
    """
    if total_words <= 0:
        return []

    minimum_chunks = math.ceil(total_words / DOC_MAX)
    target_chunks = max(1, round(total_words / DOC_TARGET))
    count = max(minimum_chunks, target_chunks)

    base, remainder = divmod(total_words, count)

    sizes = [
        base + (1 if index < remainder else 0)
        for index in range(count)
    ]

    if max(sizes) > DOC_MAX:
        raise RuntimeError(
            f"Chunking invariant failed: {max(sizes)} > {DOC_MAX}"
        )

    if sum(sizes) != total_words:
        raise RuntimeError(
            "Chunking invariant failed: total word count changed."
        )

    return sizes


def chunk_ranges(
    stream: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """
    Use balanced strict-max sizes, nudging interior boundaries up to 20 words
    toward a block boundary when doing so cannot make either adjacent chunk
    exceed DOC_MAX.
    """
    sizes = balanced_sizes(len(stream))

    if not sizes:
        return []

    boundaries = []
    position = 0

    for size in sizes[:-1]:
        position += size
        boundaries.append(position)

    # Nudge boundaries independently, then revalidate all resulting sizes.
    for index, nominal in enumerate(list(boundaries)):
        previous = boundaries[index - 1] if index else 0
        following = (
            boundaries[index + 1]
            if index + 1 < len(boundaries)
            else len(stream)
        )

        low = max(
            previous + 1,
            nominal - 20,
            following - DOC_MAX,
        )

        high = min(
            following - 1,
            nominal + 20,
            previous + DOC_MAX,
        )

        candidates = [
            end
            for end in range(low, high + 1)
            if stream[end - 1].get("break_after")
        ]

        if candidates:
            boundaries[index] = min(
                candidates,
                key=lambda end: (
                    abs(end - nominal),
                    end,
                ),
            )

    points = [0] + boundaries + [len(stream)]

    ranges = [
        (points[index], points[index + 1])
        for index in range(len(points) - 1)
    ]

    # Hard checks. If nudging caused a violation, fall back to exact balanced
    # ranges rather than ever producing an oversize chunk.
    if any(
        end <= start or (end - start) > DOC_MAX
        for start, end in ranges
    ):
        ranges = []
        start = 0

        for size in sizes:
            end = start + size
            ranges.append((start, end))
            start = end

    flattened = [
        index
        for start, end in ranges
        for index in range(start, end)
    ]

    if flattened != list(range(len(stream))):
        raise RuntimeError(
            "Chunk ranges are not contiguous and lossless."
        )

    if any(
        (end - start) > DOC_MAX
        for start, end in ranges
    ):
        raise RuntimeError(
            "Hard document maximum violated."
        )

    return ranges


def heading_metadata(
    words: list[dict[str, Any]],
) -> tuple[
    str | None,
    list[str],
    list[list[str]],
]:
    paths = stable_unique(
        [
            list(word.get("heading_path") or ())
            for word in words
            if word.get("heading_path")
        ]
    )

    first_path = (
        list(words[0].get("heading_path") or ())
        if words
        else []
    )

    current_heading = first_path[-1] if first_path else None

    headings = stable_unique(
        [
            path[-1]
            for path in paths
            if path
        ]
    )

    return current_heading, headings, paths


# ============================================================================
# Build page + Substack chunks
# ============================================================================

def page_source_id(page: dict[str, Any]) -> str:
    source_id = clean_space(page.get("id"))

    if not source_id:
        raise RuntimeError("PageRecord missing id.")

    return source_id


def page_markdown(page: dict[str, Any]) -> str:
    body = page.get("content_markdown") or ""

    if clean_space(body):
        return body

    return page.get("summary_markdown") or ""


def page_url(page: dict[str, Any]) -> str:
    if page.get("path"):
        return clean_space(page["path"])

    source = page.get("source") or {}

    if isinstance(source, dict):
        return clean_space(source.get("url"))

    return ""


def build_document_chunks(
    *,
    record_type: str,
    source_id: str,
    source_key_prefix: str,
    title: str,
    url: str,
    markdown: str,
    section: str | None,
    topic: str | None,
    topics: list[Any],
    tags: list[Any],
    published_at: Any,
    updated_at: Any,
    priority: Any,
) -> list[dict[str, Any]]:
    stream = markdown_word_stream(markdown)
    ranges = chunk_ranges(stream)
    output = []

    for chunk_index, (start, end) in enumerate(ranges):
        words = stream[start:end]
        text = " ".join(word["word"] for word in words)
        wc = word_count(text)

        heading, headings, heading_paths = heading_metadata(words)

        flags = []

        if wc < DOC_MIN:
            flags.append("short_chunk_unavoidable")

        source_key = (
            f"{source_key_prefix}:chunk:{chunk_index + 1:04d}"
        )

        output.append({
            "schema_version": 1,
            "record_type": record_type,
            "ref_id": None,
            "source_key": source_key,
            "source_id": source_id,
            "chunk_index": chunk_index,
            "title": title,
            "url": url,
            "section": section,
            "topic": topic,
            "topics": topics,
            "tags": tags,
            "heading": heading,
            "headings": headings,
            "heading_paths": heading_paths,
            "published_at": published_at,
            "updated_at": updated_at,
            "priority": priority,
            "word_count": wc,
            "text": text,
            "text_sha256": sha256_text(text),
            "source_word_start": start,
            "source_word_end": end - 1,
            "source_word_count": len(stream),
            "qc_flags": flags,
        })

    source_text = " ".join(word["word"] for word in stream)
    rebuilt = " ".join(chunk["text"] for chunk in output)

    if source_text != rebuilt:
        raise RuntimeError(
            f"Chunking lost or duplicated text for {source_key_prefix}."
        )

    return output


def build_page_chunks(page: dict[str, Any]) -> list[dict[str, Any]]:
    source_id = page_source_id(page)

    return build_document_chunks(
        record_type="page_chunk",
        source_id=source_id,
        source_key_prefix=f"page:{source_id}",
        title=clean_space(page.get("title")),
        url=page_url(page),
        markdown=page_markdown(page),
        section=page.get("section"),
        topic=page.get("topic"),
        topics=page.get("topics") or [],
        tags=[],
        published_at=page.get("publication_date"),
        updated_at=page.get("updated_date"),
        priority=page.get("priority"),
    )


def build_substack_chunks(
    post: dict[str, Any],
) -> list[dict[str, Any]]:
    post_id = clean_space(post.get("post_id"))

    if not post_id:
        raise RuntimeError("Substack record missing post_id.")

    source_id = f"substack:{post_id}"

    return build_document_chunks(
        record_type="substack_chunk",
        source_id=source_id,
        source_key_prefix=f"substack:{post_id}",
        title=clean_space(post.get("title")),
        url=clean_space(post.get("url")),
        markdown=post.get("content_markdown") or "",
        section="substack",
        topic=None,
        topics=post.get("topics") or [],
        tags=post.get("tags") or [],
        published_at=post.get("published_at"),
        updated_at=post.get("updated_at"),
        priority=post.get("priority"),
    )


# ============================================================================
# Universal persistent ref registry
# ============================================================================

def family_for_ref(ref_id: int) -> str:
    if NEWS_MIN <= ref_id <= NEWS_MAX:
        return "news"

    if DOCUMENT_MIN <= ref_id <= DOCUMENT_MAX:
        return "document"

    if ref_id >= YOUTUBE_MIN:
        return "youtube"

    return "reserved"


def load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    rows = load_jsonl(path)
    refs = set()
    keys = set()

    for row in rows:
        ref_id = row.get("ref_id")
        source_key = row.get("source_key")
        family = row.get("family")

        if not isinstance(ref_id, int):
            raise RuntimeError(
                f"Registry has non-integer ref_id: {ref_id!r}"
            )

        if not isinstance(source_key, str) or not source_key:
            raise RuntimeError(
                f"Registry has invalid source_key: {source_key!r}"
            )

        if ref_id in refs:
            raise RuntimeError(
                f"Duplicate registry ref_id: {ref_id}"
            )

        if source_key in keys:
            raise RuntimeError(
                f"Duplicate registry source_key: {source_key}"
            )

        expected = family_for_ref(ref_id)

        if expected == "reserved" or expected != family:
            raise RuntimeError(
                f"Registry range/family mismatch: "
                f"ref_id={ref_id}, family={family!r}, "
                f"expected={expected!r}"
            )

        refs.add(ref_id)
        keys.add(source_key)

    return rows


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
            f"Invalid news ArticleID: {value!r}"
        ) from exc

    if not (NEWS_MIN <= result <= NEWS_MAX):
        raise RuntimeError(
            f"News ArticleID {result} is outside 1..99,999."
        )

    return result


def youtube_source_key(chunk: dict[str, Any]) -> str:
    video_id = clean_space(chunk.get("video_id"))
    index = chunk.get("chunk_index")

    if not video_id or not isinstance(index, int):
        raise RuntimeError(
            "YouTube chunk missing video_id/chunk_index."
        )

    return f"youtube:{video_id}:chunk:{index + 1:04d}"


def desired_registry_rows(
    article_index: list[dict[str, Any]],
    document_chunks: list[dict[str, Any]],
    youtube_chunks: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    news = []

    for article in article_index:
        aid = article_id(article)

        news.append({
            "schema_version": 1,
            "ref_id": aid,
            "family": "news",
            "record_type": "news",
            "source_key": f"news:{aid}",
            "source_id": str(aid),
            "chunk_index": None,
            "active": True,
        })

    documents = [
        {
            "schema_version": 1,
            "ref_id": None,
            "family": "document",
            "record_type": chunk["record_type"],
            "source_key": chunk["source_key"],
            "source_id": chunk["source_id"],
            "chunk_index": chunk["chunk_index"],
            "active": True,
        }
        for chunk in document_chunks
    ]

    youtube = [
        {
            "schema_version": 1,
            "ref_id": None,
            "family": "youtube",
            "record_type": "youtube_chunk",
            "source_key": youtube_source_key(chunk),
            "source_id": clean_space(chunk.get("video_id")),
            "chunk_index": chunk["chunk_index"],
            "active": True,
        }
        for chunk in youtube_chunks
    ]

    return news, documents, youtube


def next_ref(
    existing: list[dict[str, Any]],
    family: str,
) -> int:
    used = [
        row["ref_id"]
        for row in existing
        if row.get("family") == family
    ]

    if family == "document":
        value = max(used) + 1 if used else DOCUMENT_MIN

        if value > DOCUMENT_MAX:
            raise RuntimeError(
                "Document ref_id namespace exhausted."
            )

        return value

    if family == "youtube":
        return max(used) + 1 if used else YOUTUBE_MIN

    raise ValueError(f"Unsupported family: {family}")


def merge_registry(
    existing: list[dict[str, Any]],
    desired_news: list[dict[str, Any]],
    desired_documents: list[dict[str, Any]],
    desired_youtube: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    by_key = {
        row["source_key"]: dict(row)
        for row in existing
    }

    by_ref = {
        row["ref_id"]: row["source_key"]
        for row in existing
    }

    # Retain old allocations but mark inactive unless rediscovered.
    for row in by_key.values():
        row["active"] = False

    stats = {
        "allocated_news": 0,
        "allocated_document": 0,
        "allocated_youtube": 0,
        "reused_news": 0,
        "reused_document": 0,
        "reused_youtube": 0,
    }

    # News IDs are fixed by ArticleID.
    for desired in sorted(
        desired_news,
        key=lambda row: row["ref_id"],
    ):
        key = desired["source_key"]
        fixed_ref = desired["ref_id"]

        if key in by_key:
            current = by_key[key]

            if current["ref_id"] != fixed_ref:
                raise RuntimeError(
                    f"News ref mismatch for {key}: "
                    f"{current['ref_id']} != {fixed_ref}"
                )

            current.update(desired)
            stats["reused_news"] += 1
            continue

        occupied = by_ref.get(fixed_ref)

        if occupied and occupied != key:
            raise RuntimeError(
                f"News ref_id {fixed_ref} already belongs to {occupied}."
            )

        by_key[key] = dict(desired)
        by_ref[fixed_ref] = key
        stats["allocated_news"] += 1

    next_doc = next_ref(existing, "document")

    for desired in sorted(
        desired_documents,
        key=lambda row: (
            0 if row["record_type"] == "page_chunk" else 1,
            row["source_id"],
            row["chunk_index"],
        ),
    ):
        key = desired["source_key"]

        if key in by_key:
            current = by_key[key]

            if current.get("family") != "document":
                raise RuntimeError(
                    f"Registry family changed for {key}."
                )

            desired["ref_id"] = current["ref_id"]
            current.update(desired)
            stats["reused_document"] += 1
            continue

        while next_doc in by_ref:
            next_doc += 1

        if next_doc > DOCUMENT_MAX:
            raise RuntimeError(
                "Document ref_id namespace exhausted."
            )

        desired["ref_id"] = next_doc
        by_key[key] = dict(desired)
        by_ref[next_doc] = key
        stats["allocated_document"] += 1
        next_doc += 1

    next_video = next_ref(existing, "youtube")

    for desired in sorted(
        desired_youtube,
        key=lambda row: (
            row["source_id"],
            row["chunk_index"],
        ),
    ):
        key = desired["source_key"]

        if key in by_key:
            current = by_key[key]

            if current.get("family") != "youtube":
                raise RuntimeError(
                    f"Registry family changed for {key}."
                )

            desired["ref_id"] = current["ref_id"]
            current.update(desired)
            stats["reused_youtube"] += 1
            continue

        while next_video in by_ref:
            next_video += 1

        desired["ref_id"] = next_video
        by_key[key] = dict(desired)
        by_ref[next_video] = key
        stats["allocated_youtube"] += 1
        next_video += 1

    registry = sorted(
        by_key.values(),
        key=lambda row: row["ref_id"],
    )

    # Final uniqueness/range check.
    refs = set()
    keys = set()

    for row in registry:
        ref_id = row["ref_id"]
        key = row["source_key"]

        if ref_id in refs:
            raise RuntimeError(
                f"Duplicate ref_id after merge: {ref_id}"
            )

        if key in keys:
            raise RuntimeError(
                f"Duplicate source_key after merge: {key}"
            )

        if family_for_ref(ref_id) != row["family"]:
            raise RuntimeError(
                f"Range/family mismatch after merge: {ref_id}"
            )

        refs.add(ref_id)
        keys.add(key)

    stats["inactive"] = sum(
        not row.get("active", False)
        for row in registry
    )

    return registry, stats


def active_ref_lookup(
    registry: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        row["source_key"]: row["ref_id"]
        for row in registry
        if row.get("active")
    }


# ============================================================================
# Attach refs + validation
# ============================================================================

def attach_document_refs(
    chunks: list[dict[str, Any]],
    refs: dict[str, int],
) -> list[dict[str, Any]]:
    output = []

    for chunk in chunks:
        key = chunk["source_key"]

        if key not in refs:
            raise RuntimeError(
                f"Missing document ref for {key}."
            )

        row = dict(chunk)
        row["ref_id"] = refs[key]
        output.append(row)

    return sorted(output, key=lambda row: row["ref_id"])


def build_youtube_search_chunks(
    canonical: list[dict[str, Any]],
    refs: dict[str, int],
) -> list[dict[str, Any]]:
    output = []

    for chunk in canonical:
        key = youtube_source_key(chunk)

        if key not in refs:
            raise RuntimeError(
                f"Missing YouTube ref for {key}."
            )

        output.append({
            "schema_version": 1,
            "ref_id": refs[key],
            "source_key": key,
            **chunk,
        })

    return sorted(output, key=lambda row: row["ref_id"])


def validate_document_chunks(
    chunks: list[dict[str, Any]],
) -> list[str]:
    errors = []
    seen_refs = set()
    seen_keys = set()

    for chunk in chunks:
        ref_id = chunk.get("ref_id")
        key = chunk.get("source_key")
        wc = chunk.get("word_count")
        actual_wc = word_count(chunk.get("text") or "")

        if (
            not isinstance(ref_id, int)
            or not (DOCUMENT_MIN <= ref_id <= DOCUMENT_MAX)
        ):
            errors.append(
                f"{key}: invalid document ref_id {ref_id!r}"
            )

        if ref_id in seen_refs:
            errors.append(
                f"duplicate document ref_id {ref_id}"
            )

        if key in seen_keys:
            errors.append(
                f"duplicate document source_key {key}"
            )

        seen_refs.add(ref_id)
        seen_keys.add(key)

        if wc != actual_wc:
            errors.append(
                f"{key}: word_count {wc} != actual {actual_wc}"
            )

        if isinstance(wc, int) and wc > DOC_MAX:
            errors.append(
                f"{key}: hard maximum exceeded ({wc})"
            )

        flags = set(chunk.get("qc_flags") or [])

        if (
            isinstance(wc, int)
            and wc < DOC_MIN
            and "short_chunk_unavoidable" not in flags
        ):
            errors.append(
                f"{key}: short chunk missing QC flag"
            )

        if chunk.get("text_sha256") != sha256_text(
            chunk.get("text") or ""
        ):
            errors.append(
                f"{key}: text_sha256 mismatch"
            )

    return errors


def validate_youtube_search_chunks(
    chunks: list[dict[str, Any]],
) -> list[str]:
    errors = []
    seen_refs = set()
    seen_keys = set()

    for chunk in chunks:
        ref_id = chunk.get("ref_id")
        key = chunk.get("source_key")
        wc = chunk.get("word_count")

        if not isinstance(ref_id, int) or ref_id < YOUTUBE_MIN:
            errors.append(
                f"{key}: invalid YouTube ref_id {ref_id!r}"
            )

        if ref_id in seen_refs:
            errors.append(
                f"duplicate YouTube ref_id {ref_id}"
            )

        if key in seen_keys:
            errors.append(
                f"duplicate YouTube source_key {key}"
            )

        seen_refs.add(ref_id)
        seen_keys.add(key)

        if isinstance(wc, int) and wc > 320:
            errors.append(
                f"{key}: canonical YouTube chunk exceeds 320 words"
            )

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

    pages_path = corpus / "pages-v1.jsonl"
    substack_path = corpus / "substack-master-v1.jsonl"
    youtube_path = corpus / "youtube-chunks-v1.jsonl"
    article_index_path = data / "article-index.jsonl"

    registry_path = corpus / "ref-registry-v1.jsonl"
    docs_output = corpus / "document-chunks-v1.jsonl"
    youtube_output = corpus / "youtube-search-chunks-v1.jsonl"

    report_path = (
        root
        / "reports"
        / "build"
        / "search-corpus-build.json"
    )

    for path in (
        pages_path,
        substack_path,
        youtube_path,
        article_index_path,
    ):
        if not path.exists():
            raise RuntimeError(
                f"Missing required input: {path}"
            )

    print()
    print("Loading canonical corpora...")

    pages = load_jsonl(pages_path)
    substack = load_jsonl(substack_path)
    youtube = load_jsonl(youtube_path)
    articles = load_jsonl(article_index_path)

    print("Chunking PageRecord corpus...")

    page_chunks = []

    for page in sorted(
        pages,
        key=lambda row: (
            clean_space(row.get("id")),
            clean_space(row.get("path")),
        ),
    ):
        page_chunks.extend(
            build_page_chunks(page)
        )

    print("Chunking Substack corpus...")

    substack_chunks = []

    for post in sorted(
        substack,
        key=lambda row: (
            int(row["post_id"])
            if str(row.get("post_id", "")).isdigit()
            else 10**30,
            clean_space(row.get("post_id")),
        ),
    ):
        substack_chunks.extend(
            build_substack_chunks(post)
        )

    document_chunks = page_chunks + substack_chunks

    existing_registry = load_registry(registry_path)

    desired_news, desired_docs, desired_youtube = (
        desired_registry_rows(
            articles,
            document_chunks,
            youtube,
        )
    )

    print("Allocating/reusing universal ref_ids...")

    registry, registry_stats = merge_registry(
        existing_registry,
        desired_news,
        desired_docs,
        desired_youtube,
    )

    refs = active_ref_lookup(registry)

    document_chunks = attach_document_refs(
        document_chunks,
        refs,
    )

    youtube_search = build_youtube_search_chunks(
        youtube,
        refs,
    )

    doc_errors = validate_document_chunks(
        document_chunks
    )

    youtube_errors = validate_youtube_search_chunks(
        youtube_search
    )

    errors = doc_errors + youtube_errors

    document_word_counts = [
        row["word_count"]
        for row in document_chunks
    ]

    report = {
        "build_type": "search-corpus-v1",
        "built_at": now_iso(),
        "chunking": {
            "minimum_words_soft": DOC_MIN,
            "target_words": DOC_TARGET,
            "maximum_words_hard": DOC_MAX,
        },
        "ref_ranges": {
            "news": [NEWS_MIN, NEWS_MAX],
            "document": [DOCUMENT_MIN, DOCUMENT_MAX],
            "youtube": [YOUTUBE_MIN, None],
        },
        "source_counts": {
            "pages": len(pages),
            "substack_posts": len(substack),
            "youtube_chunks": len(youtube),
            "news_articles": len(desired_news),
        },
        "derived_counts": {
            "page_chunks": len(page_chunks),
            "substack_chunks": len(substack_chunks),
            "document_chunks": len(document_chunks),
            "youtube_search_chunks": len(youtube_search),
            "registry_rows": len(registry),
            "registry_active": sum(
                bool(row.get("active"))
                for row in registry
            ),
            "registry_inactive": sum(
                not bool(row.get("active"))
                for row in registry
            ),
        },
        "registry": registry_stats,
        "document_chunk_stats": {
            "minimum_words": min(document_word_counts, default=0),
            "maximum_words": max(document_word_counts, default=0),
            "average_words": round(
                sum(document_word_counts)
                / max(1, len(document_word_counts)),
                2,
            ),
            "short_chunks": sum(
                count < DOC_MIN
                for count in document_word_counts
            ),
            "over_max": sum(
                count > DOC_MAX
                for count in document_word_counts
            ),
            "qc_flags": qc_summary(document_chunks),
        },
        "validation": {
            "errors": len(errors),
            "document_errors": doc_errors[:100],
            "youtube_errors": youtube_errors[:100],
        },
        "outputs": {
            "document_chunks": str(docs_output),
            "youtube_search_chunks": str(youtube_output),
            "ref_registry": str(registry_path),
            "report": str(report_path),
        },
    }

    write_json(report_path, report)

    if errors:
        print()
        print("SEARCH CORPUS BUILD FAILED")
        print(f"Validation errors: {len(errors):,}")
        print(f"Report: {report_path}")
        raise SystemExit(1)

    # Only write derived corpus/registry after all validation passes.
    write_jsonl(docs_output, document_chunks)
    write_jsonl(youtube_output, youtube_search)
    write_jsonl(registry_path, registry)

    active_news = sum(
        row.get("active") and row.get("family") == "news"
        for row in registry
    )

    active_docs = sum(
        row.get("active") and row.get("family") == "document"
        for row in registry
    )

    active_youtube = sum(
        row.get("active") and row.get("family") == "youtube"
        for row in registry
    )

    print()
    print("======================================")
    print("SEARCH CORPUS BUILD COMPLETE")
    print("======================================")
    print(f"Pages:                    {len(pages):,}")
    print(f"Page chunks:              {len(page_chunks):,}")
    print(f"Substack posts:           {len(substack):,}")
    print(f"Substack chunks:          {len(substack_chunks):,}")
    print(f"Document chunks total:    {len(document_chunks):,}")
    print(f"YouTube chunks:           {len(youtube_search):,}")
    print()
    print(
        f"Document min words:       "
        f"{report['document_chunk_stats']['minimum_words']:,}"
    )
    print(
        f"Document max words:       "
        f"{report['document_chunk_stats']['maximum_words']:,}"
    )
    print(
        f"Document avg words:       "
        f"{report['document_chunk_stats']['average_words']}"
    )
    print(
        f"Short document chunks:    "
        f"{report['document_chunk_stats']['short_chunks']:,}"
    )
    print(
        f"Document chunks >320:     "
        f"{report['document_chunk_stats']['over_max']:,}"
    )
    print()
    print(f"Active news refs:         {active_news:,}")
    print(f"Active document refs:     {active_docs:,}")
    print(f"Active YouTube refs:      {active_youtube:,}")
    print(
        f"Inactive retained refs:   "
        f"{report['derived_counts']['registry_inactive']:,}"
    )
    print()
    print(
        f"New document refs:        "
        f"{registry_stats['allocated_document']:,}"
    )
    print(
        f"Reused document refs:     "
        f"{registry_stats['reused_document']:,}"
    )
    print(
        f"New YouTube refs:         "
        f"{registry_stats['allocated_youtube']:,}"
    )
    print(
        f"Reused YouTube refs:      "
        f"{registry_stats['reused_youtube']:,}"
    )
    print()
    print("Outputs:")
    print(f"  {docs_output}")
    print(f"  {youtube_output}")
    print(f"  {registry_path}")
    print()
    print(f"Build report: {report_path}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        print()
        print("SEARCH CORPUS BUILD FAILED", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        raise
