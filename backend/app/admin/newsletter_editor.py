from __future__ import annotations

import re
import sqlite3
from typing import Any

from .article_edit import update_article
from .article_store import article_hash, row_to_article
from .article_withdrawal import pending_withdrawal_for_article
from .image_staging import has_staged_image
from .newsletter_render import newsletter_article_content


FIELD_NAMES = (
    "title",
    "headlines",
    "regular_preview_items",
    "inspiring_preview_items",
    "special_note_markdown",
)

ARTICLE_BLOCK_RE = re.compile(
    r"<!-- WTK:ARTICLE (?P<id>\d+) START -->\s*"
    r"(?P<body>.*?)\s*"
    r"<!-- WTK:ARTICLE (?P=id) END -->",
    re.DOTALL,
)


class NewsletterEditorError(ValueError):
    """Raised when the editable newsletter document is malformed."""


class NewsletterEditorConflict(RuntimeError):
    """Raised when an article changed after the newsletter editor loaded."""


def _field_markers(name: str) -> tuple[str, str]:
    if name not in FIELD_NAMES:
        raise ValueError(f"Unknown newsletter field marker: {name}")
    return (
        f"<!-- WTK:FIELD {name} START -->",
        f"<!-- WTK:FIELD {name} END -->",
    )


def _section_markers(name: str) -> tuple[str, str]:
    if name not in {"regular", "inspiring"}:
        raise ValueError(f"Unknown newsletter section marker: {name}")
    return (
        f"<!-- WTK:SECTION {name} START -->",
        f"<!-- WTK:SECTION {name} END -->",
    )


def _extract_between(text: str, start: str, end: str, label: str) -> str:
    start_count = text.count(start)
    end_count = text.count(end)

    if start_count != 1 or end_count != 1:
        raise NewsletterEditorError(
            f"{label} markers are missing or duplicated. "
            "Reload the editor to restore the document structure."
        )

    before, remainder = text.split(start, 1)
    body, after = remainder.split(end, 1)

    if end in before or start in after:
        raise NewsletterEditorError(f"Invalid marker order for {label}.")

    return body.strip("\n")


def _field(text: str, name: str) -> str:
    start, end = _field_markers(name)
    return _extract_between(text, start, end, name.replace("_", " "))


def _section(text: str, name: str) -> str:
    start, end = _section_markers(name)
    return _extract_between(text, start, end, f"{name} article section")


def _parse_title(block: str) -> str:
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if len(lines) > 1:
        raise NewsletterEditorError(
            "The newsletter title block must contain a single Markdown heading."
        )
    if not lines:
        return ""

    line = lines[0]
    if line == "#":
        return ""
    if not line.startswith("# "):
        raise NewsletterEditorError(
            "The newsletter title must remain a level-one Markdown heading beginning with '# '."
        )
    return line[2:].strip()


def _parse_bullets(block: str, label: str, *, limit: int | None = None) -> list[str]:
    values: list[str] = []

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if not line.startswith("- "):
            raise NewsletterEditorError(
                f"{label} must remain a Markdown bullet list using '- '."
            )
        value = line[2:].strip()
        if value:
            values.append(value)

    if limit is not None and len(values) > limit:
        raise NewsletterEditorError(
            f"{label} may contain at most {limit} items."
        )

    return values


def _article_summary(block: str, article_id: str) -> str:
    start = f"<!-- WTK:ARTICLE {article_id} SUMMARY START -->"
    end = f"<!-- WTK:ARTICLE {article_id} SUMMARY END -->"
    return _extract_between(
        block,
        start,
        end,
        f"article {article_id} summary",
    ).strip()


def _article_note(block: str, article_id: str) -> str:
    start = f"<!-- WTK:ARTICLE {article_id} NOTE START -->"
    end = f"<!-- WTK:ARTICLE {article_id} NOTE END -->"
    return _extract_between(
        block,
        start,
        end,
        f"article {article_id} note",
    ).strip()


def _article_title(block: str, article_id: str) -> str:
    summary_start = f"<!-- WTK:ARTICLE {article_id} SUMMARY START -->"
    prefix = block.split(summary_start, 1)[0]

    headings = [
        line.strip()[4:].strip()
        for line in prefix.splitlines()
        if line.strip().startswith("### ")
    ]

    if len(headings) != 1:
        raise NewsletterEditorError(
            f"Article {article_id} must retain exactly one '###' title heading."
        )

    return headings[0]


def _parse_article_section(
    block: str,
    *,
    section_name: str,
    expected_ids: list[str],
    article_states: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, dict[str, str]]]:
    matches = list(ARTICLE_BLOCK_RE.finditer(block))
    ids = [match.group("id") for match in matches]

    if len(ids) != len(set(ids)):
        raise NewsletterEditorError(
            f"The {section_name} section contains a duplicate article block."
        )

    expected_set = set(expected_ids)
    actual_set = set(ids)

    if actual_set != expected_set:
        missing = sorted(expected_set - actual_set, key=int)
        unexpected = sorted(actual_set - expected_set, key=int)

        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append("unexpected: " + ", ".join(unexpected))

        raise NewsletterEditorError(
            f"The {section_name} article selection changed inside the Markdown editor "
            f"({'; '.join(details)}). Add/remove articles in the Newsletter Builder instead."
        )

    content: dict[str, dict[str, str]] = {}

    for match in matches:
        article_id = match.group("id")
        article_block = match.group("body")
        state = article_states.get(article_id)

        if state is None:
            raise NewsletterEditorError(
                f"Article {article_id} is no longer available in the admin database."
            )

        shown_title = _article_title(article_block, article_id)
        expected_title = str(state.get("title", "")).strip()

        if shown_title != expected_title:
            raise NewsletterEditorError(
                f"Article {article_id} title was changed in the newsletter document. "
                "Open the article editor to change a canonical article title."
            )

        content[article_id] = {
            "summary_markdown": _article_summary(article_block, article_id),
            "note_markdown": _article_note(article_block, article_id),
        }

    # Anything outside article blocks must only be the section heading/whitespace.
    residual = ARTICLE_BLOCK_RE.sub("", block)
    residual_lines = [
        line.strip()
        for line in residual.splitlines()
        if line.strip()
    ]
    allowed_heading = (
        "## Regular Articles"
        if section_name == "regular"
        else "## Inspiring Articles"
    )
    if residual_lines not in ([], [allowed_heading]):
        raise NewsletterEditorError(
            f"Unexpected text was added outside article blocks in the {section_name} section."
        )

    return ids, content


def parse_editor_document(
    document: str,
    *,
    newsletter: dict[str, Any],
    article_states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    document = str(document or "")

    if not document.strip():
        raise NewsletterEditorError("Newsletter document is empty.")

    title = _parse_title(_field(document, "title"))
    headlines = _parse_bullets(
        _field(document, "headlines"),
        "Headlines",
        limit=3,
    )
    regular_preview_items = _parse_bullets(
        _field(document, "regular_preview_items"),
        "Regular preview items",
    )
    inspiring_preview_items = _parse_bullets(
        _field(document, "inspiring_preview_items"),
        "Inspiring preview items",
    )
    special_note_markdown = _field(
        document,
        "special_note_markdown",
    ).strip()

    regular_ids, regular_content = _parse_article_section(
        _section(document, "regular"),
        section_name="regular",
        expected_ids=[
            str(value)
            for value in newsletter.get("regular_article_ids", [])
        ],
        article_states=article_states,
    )

    inspiring_ids, inspiring_content = _parse_article_section(
        _section(document, "inspiring"),
        section_name="inspiring",
        expected_ids=[
            str(value)
            for value in newsletter.get("inspiring_article_ids", [])
        ],
        article_states=article_states,
    )

    article_content = {
        **regular_content,
        **inspiring_content,
    }

    return {
        "title": title,
        "headlines": headlines,
        "regular_preview_items": regular_preview_items,
        "inspiring_preview_items": inspiring_preview_items,
        "special_note_markdown": special_note_markdown,
        "regular_article_ids": regular_ids,
        "inspiring_article_ids": inspiring_ids,
        "article_content": article_content,
    }


def _field_block(name: str, body: str) -> str:
    start, end = _field_markers(name)
    return f"{start}\n{body.rstrip()}\n{end}"


def _bullet_block(values: list[str]) -> str:
    return "\n".join(
        f"- {str(value).strip()}"
        for value in values
        if str(value).strip()
    )


def _article_block(article_id: str, state: dict[str, Any]) -> str:
    title = str(state.get("title", "")).strip()
    summary = str(state.get("summary_markdown", "")).strip()
    note = str(state.get("note_markdown", "")).strip()

    return "\n".join(
        [
            f"<!-- WTK:ARTICLE {article_id} START -->",
            f"### {title}",
            f"<!-- WTK:ARTICLE {article_id} SUMMARY START -->",
            summary,
            f"<!-- WTK:ARTICLE {article_id} SUMMARY END -->",
            "",
            "#### WTK Note",
            f"<!-- WTK:ARTICLE {article_id} NOTE START -->",
            note,
            f"<!-- WTK:ARTICLE {article_id} NOTE END -->",
            f"<!-- WTK:ARTICLE {article_id} END -->",
        ]
    )


def _section_block(
    name: str,
    article_ids: list[str],
    article_states: dict[str, dict[str, Any]],
) -> str:
    start, end = _section_markers(name)
    heading = "Regular Articles" if name == "regular" else "Inspiring Articles"

    blocks = [
        _article_block(article_id, article_states[article_id])
        for article_id in article_ids
    ]

    content = "\n\n".join([f"## {heading}", *blocks]).rstrip()

    return f"{start}\n{content}\n{end}"


def render_editor_document(
    newsletter: dict[str, Any],
    article_states: dict[str, dict[str, Any]],
) -> str:
    title = str(newsletter.get("title", "")).strip()

    parts = [
        _field_block("title", f"# {title}" if title else "#"),
        _field_block(
            "headlines",
            _bullet_block(list(newsletter.get("headlines", []))),
        ),
        _field_block(
            "regular_preview_items",
            _bullet_block(
                list(newsletter.get("regular_preview_items", []))
            ),
        ),
        _section_block(
            "regular",
            [
                str(value)
                for value in newsletter.get("regular_article_ids", [])
            ],
            article_states,
        ),
        _field_block(
            "inspiring_preview_items",
            _bullet_block(
                list(newsletter.get("inspiring_preview_items", []))
            ),
        ),
        _section_block(
            "inspiring",
            [
                str(value)
                for value in newsletter.get("inspiring_article_ids", [])
            ],
            article_states,
        ),
        "## Special Note\n\n"
        + _field_block(
            "special_note_markdown",
            str(newsletter.get("special_note_markdown", "")).strip(),
        ),
    ]

    return "\n\n".join(parts).rstrip() + "\n"


def _article_update_payload(
    article: dict[str, Any],
    *,
    summary_markdown: str,
    note_markdown: str,
) -> dict[str, Any]:
    return {
        "title": str(article.get("title", "")),
        "slug": str(article.get("slug", "")),
        "legacy_url": str(article.get("legacy_url", "")),
        "publication_date": str(article.get("publication_date", "")),
        "posted_date": str(article.get("posted_date", "")),
        "publication_group": str(article.get("publication_group", "")),
        "publication_detail": str(article.get("publication_detail", "")),
        "publication_raw": str(article.get("publication_raw", "")),
        "source_url": str(article.get("source_url", "")),
        "summary_markdown": summary_markdown,
        "note_markdown": note_markdown,
        "tags": list(article.get("tags", [])),
        "priority": int(article.get("priority", 0) or 0),
        "image_caption_markdown": str(
            article.get("image_caption_markdown", "")
        ),
        "image_caption_text": str(
            article.get("image_caption_text", "")
        ),
    }


def load_article_states(
    conn: sqlite3.Connection,
    article_ids: list[str],
) -> dict[str, dict[str, Any]]:
    unique_ids = list(dict.fromkeys(str(value) for value in article_ids))
    canonical = newsletter_article_content(unique_ids)
    result: dict[str, dict[str, Any]] = {}

    for article_id in unique_ids:
        row = conn.execute(
            "SELECT * FROM articles WHERE article_id = ?",
            (int(article_id),),
        ).fetchone()

        if row is None:
            raise NewsletterEditorError(
                f"Article {article_id} is missing from the admin database."
            )

        article = row_to_article(row)
        canonical_article = canonical[article_id]

        result[article_id] = {
            "article_id": article_id,
            "title": canonical_article["title"],
            "summary_markdown": str(
                article.get("summary_markdown", "")
            ),
            "canonical_summary_markdown": str(
                canonical_article.get("summary_markdown", "")
            ),
            "note_markdown": str(
                article.get("note_markdown", "")
            ),
            "canonical_note_markdown": str(
                canonical_article.get("note_markdown", "")
            ),
            "admin_updated_at": str(
                row["admin_updated_at"] or ""
            ),
            "edit_state": str(row["edit_state"] or ""),
            "workflow_state": str(row["workflow_state"] or ""),
            "canonical_hash": str(row["canonical_hash"] or ""),
            "current_hash": article_hash(article),
            "_article": article,
        }

    return result


def _state_token(state: dict[str, Any]) -> str:
    return (
        f"{str(state.get('admin_updated_at', ''))}:"
        f"{str(state.get('current_hash', ''))}"
    )


def article_tokens(
    article_states: dict[str, dict[str, Any]],
) -> dict[str, str]:
    return {
        article_id: _state_token(state)
        for article_id, state in article_states.items()
    }


def _lineage_is_safe(
    conn: sqlite3.Connection,
    article_id: str,
    state: dict[str, Any],
    receipt: dict[str, Any] | None,
) -> tuple[bool, str]:
    article_number = int(article_id)

    if has_staged_image(conn, article_number):
        return False, ""

    if pending_withdrawal_for_article(conn, article_number) is not None:
        return False, ""

    current_hash = str(state.get("current_hash", ""))
    canonical_hash = str(state.get("canonical_hash", ""))

    clean = (
        state.get("edit_state") == "clean"
        and state.get("workflow_state") == "published"
        and bool(canonical_hash)
        and current_hash == canonical_hash
    )

    if clean:
        return True, current_hash

    if (
        isinstance(receipt, dict)
        and bool(receipt.get("safe_to_publish"))
        and str(receipt.get("after_hash", "")) == current_hash
    ):
        return True, str(receipt.get("base_hash", ""))

    return False, ""


def apply_article_content_changes(
    conn: sqlite3.Connection,
    *,
    article_content: dict[str, dict[str, str]],
    expected_tokens: dict[str, str],
    receipts: dict[str, dict[str, Any]],
    actor: str,
) -> tuple[
    dict[str, dict[str, Any]],
    list[str],
    dict[str, dict[str, Any]],
]:
    states = load_article_states(conn, list(article_content))

    for article_id, state in states.items():
        if article_id not in expected_tokens:
            raise NewsletterEditorConflict(
                f"Missing revision token for article {article_id}. Reload the editor."
            )

        expected = str(expected_tokens.get(article_id, ""))
        actual = _state_token(state)

        if expected != actual:
            raise NewsletterEditorConflict(
                f"Article {article_id} changed after this newsletter editor was opened. "
                "Reload before saving."
            )

    updated_receipts = {
        str(article_id): dict(receipt)
        for article_id, receipt in (receipts or {}).items()
        if isinstance(receipt, dict)
    }
    changed_ids: list[str] = []

    for article_id, edited in article_content.items():
        state = states[article_id]
        new_summary = str(edited.get("summary_markdown", ""))
        new_note = str(edited.get("note_markdown", ""))
        current_summary = str(state.get("summary_markdown", ""))
        current_note = str(state.get("note_markdown", ""))

        # Remove stale receipts even when this document did not change the article.
        receipt = updated_receipts.get(article_id)
        if (
            receipt
            and str(receipt.get("after_hash", ""))
            != str(state.get("current_hash", ""))
        ):
            updated_receipts.pop(article_id, None)
            receipt = None

        if new_summary == current_summary and new_note == current_note:
            continue

        safe_to_publish, base_hash = _lineage_is_safe(
            conn,
            article_id,
            state,
            receipt,
        )

        result = update_article(
            conn,
            int(article_id),
            _article_update_payload(
                state["_article"],
                summary_markdown=new_summary,
                note_markdown=new_note,
            ),
            saved_by=actor,
        )

        changed_ids.append(article_id)

        after_article = result["article"]
        after_hash = article_hash(after_article)
        after_admin = result.get("admin") or {}

        if (
            after_admin.get("edit_state") == "clean"
            and after_admin.get("workflow_state") == "published"
        ):
            updated_receipts.pop(article_id, None)
        else:
            updated_receipts[article_id] = {
                "base_hash": base_hash,
                "after_hash": after_hash,
                "saved_at": str(
                    after_admin.get("admin_updated_at", "")
                ),
                "safe_to_publish": safe_to_publish,
            }

    new_states = load_article_states(conn, list(article_content))
    return updated_receipts, changed_ids, new_states

def publishable_editor_articles(
    conn: sqlite3.Connection,
    *,
    article_states: dict[str, dict[str, Any]],
    receipts: dict[str, dict[str, Any]],
) -> list[int]:
    publish_ids: list[int] = []
    blocked: list[str] = []

    for article_id, state in article_states.items():
        current_summary = str(state.get("summary_markdown", ""))
        canonical_summary = str(
            state.get("canonical_summary_markdown", "")
        )
        current_note = str(state.get("note_markdown", ""))
        canonical_note = str(
            state.get("canonical_note_markdown", "")
        )

        # The newsletter editor owns summary and WTK Note changes.
        if (
            current_summary == canonical_summary
            and current_note == canonical_note
        ):
            continue

        receipt = receipts.get(article_id)

        safe = (
            isinstance(receipt, dict)
            and bool(receipt.get("safe_to_publish"))
            and str(receipt.get("after_hash", ""))
            == str(state.get("current_hash", ""))
            and not has_staged_image(conn, int(article_id))
            and pending_withdrawal_for_article(
                conn,
                int(article_id),
            )
            is None
        )

        if not safe:
            blocked.append(article_id)
            continue

        if state.get("workflow_state") == "draft":
            publish_ids.append(int(article_id))

    if blocked:
        raise NewsletterEditorError(
            "These article summaries/notes cannot be safely auto-published because "
            "the articles already contain other draft/staged changes: "
            + ", ".join(sorted(blocked, key=int))
            + ". Save the newsletter, then review/publish those articles "
            "from the Article Editor."
        )

    return publish_ids
