from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup


ADMIN_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]

TEMPLATE_DIR = ADMIN_DIR / "templates"
ARTICLE_MASTER = REPO_ROOT / "src" / "site" / "data" / "wtk_articles_master.jsonl"

NEWSLETTER_TEMPLATES: dict[str, dict[str, str]] = {
    "standard": {
        "label": "Standard Newsletter",
        "template": "newsletter-email.html",
    },
}

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

_article_cache_mtime: int | None = None
_article_cache: dict[str, dict[str, Any]] = {}


def newsletter_template_choices() -> list[dict[str, str]]:
    return [
        {
            "key": key,
            "label": config["label"],
        }
        for key, config in NEWSLETTER_TEMPLATES.items()
    ]


def _template_config(template_key: str) -> dict[str, str]:
    key = str(template_key or "standard").strip() or "standard"
    try:
        return NEWSLETTER_TEMPLATES[key]
    except KeyError as exc:
        raise ValueError(f"Unknown newsletter template: {key}") from exc


def _article_map() -> dict[str, dict[str, Any]]:
    global _article_cache_mtime, _article_cache

    stat = ARTICLE_MASTER.stat()

    if _article_cache_mtime == stat.st_mtime_ns and _article_cache:
        return _article_cache

    records: dict[str, dict[str, Any]] = {}

    with ARTICLE_MASTER.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue

            row = json.loads(line)
            article_id = str(row.get("article_id", "")).strip()

            if not article_id:
                raise ValueError(
                    f"Missing article_id in master JSONL line {line_number}"
                )

            if article_id in records:
                raise ValueError(f"Duplicate article_id in master: {article_id}")

            records[article_id] = row

    _article_cache = records
    _article_cache_mtime = stat.st_mtime_ns

    return records


def newsletter_article_content(
    article_ids: list[str],
) -> dict[str, dict[str, str]]:
    """Return canonical title/summary/note content for newsletter editor use."""
    records = _article_map()
    result: dict[str, dict[str, str]] = {}

    for raw_id in article_ids:
        article_id = str(raw_id).strip()
        try:
            source = records[article_id]
        except KeyError as exc:
            raise ValueError(
                f"Newsletter references missing article ID {article_id}"
            ) from exc

        result[article_id] = {
            "article_id": article_id,
            "title": str(source.get("title", "")),
            "summary_markdown": str(source.get("summary_markdown", "")),
            "note_markdown": str(source.get("note_markdown", "")),
        }

    return result


def _markdown_block(value: str) -> Markup:
    value = str(value or "").strip()

    if not value:
        return Markup("")

    return Markup(
        markdown.markdown(
            value,
            extensions=["sane_lists"],
            output_format="html5",
        )
    )


def _markdown_inline(value: str) -> Markup:
    html = str(_markdown_block(value)).strip()

    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        html = html[3:-4]

    return Markup(html)


def _format_date(value: str) -> str:
    value = str(value or "").strip()

    if not value:
        return ""

    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%B %-d, %Y")
    except ValueError:
        return value


def _display_url(value: str, limit: int = 88) -> str:
    value = str(value or "").strip()

    if len(value) <= limit:
        return value

    return value[: limit - 3] + "..."


def _resolve_article(
    article_id: str,
    *,
    summary_override: str | None = None,
    note_override: str | None = None,
) -> dict[str, Any]:
    records = _article_map()

    try:
        source = records[str(article_id)]
    except KeyError as exc:
        raise ValueError(
            f"Newsletter references missing article ID {article_id}"
        ) from exc

    publication = (
        source.get("publication_name")
        or source.get("publication_group")
        or ""
    )

    return {
        "article_id": str(article_id),
        "title": source.get("title", ""),
        "publication_date": _format_date(
            source.get("publication_date", "")
        ),
        "publication_name": publication,
        "source_url": source.get("source_url", ""),
        "source_url_display": _display_url(
            source.get("source_url", "")
        ),
        "summary_html": _markdown_block(
            source.get("summary_markdown", "")
            if summary_override is None
            else summary_override
        ),
        "note_html": _markdown_inline(
            source.get("note_markdown", "")
            if note_override is None
            else note_override
        ),
    }


def _resolve_articles(
    article_ids: list[str],
    *,
    summary_overrides: dict[str, str] | None = None,
    note_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    summaries = summary_overrides or {}
    notes = note_overrides or {}
    return [
        _resolve_article(
            article_id,
            summary_override=summaries.get(str(article_id)),
            note_override=notes.get(str(article_id)),
        )
        for article_id in article_ids
    ]


def render_newsletter(
    newsletter: dict[str, Any],
    *,
    summary_overrides: dict[str, str] | None = None,
    note_overrides: dict[str, str] | None = None,
) -> str:
    issue_date = str(newsletter.get("issue_date", "")).strip()
    formatted_issue_date = _format_date(issue_date)

    headlines = [
        str(item).strip()
        for item in newsletter.get("headlines", [])
        if str(item).strip()
    ]

    title = str(newsletter.get("title", "")).strip()

    meta_title_parts = [part for part in [title, formatted_issue_date] if part]
    meta_title = " — ".join(meta_title_parts) or "WantToKnow.info Newsletter"

    if headlines:
        meta_description = "Key news articles on " + "; ".join(headlines) + "."
        meta_keywords = ", ".join(headlines)
    else:
        meta_description = "WantToKnow.info newsletter."
        meta_keywords = "WantToKnow.info newsletter"

    context = {
        **newsletter,
        "browser_url": str(newsletter.get("browser_url") or "").strip(),
        "formatted_issue_date": formatted_issue_date,
        "headline_items": headlines,
        "meta_title": meta_title,
        "meta_description": meta_description,
        "meta_keywords": meta_keywords,
        "special_note_html": _markdown_inline(
            newsletter.get("special_note_markdown", "")
        ),
        "regular_articles": _resolve_articles(
            newsletter.get("regular_article_ids", []),
            summary_overrides=summary_overrides,
            note_overrides=note_overrides,
        ),
        "inspiring_articles": _resolve_articles(
            newsletter.get("inspiring_article_ids", []),
            summary_overrides=summary_overrides,
            note_overrides=note_overrides,
        ),
    }

    template_key = str(newsletter.get("template_key") or "standard").strip()
    template_config = _template_config(template_key)
    template = _env.get_template(template_config["template"])
    return template.render(**context)


def newsletter_article_choices(
    query: str = "",
    *,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Return lightweight article records for the newsletter picker."""

    query = str(query or "").strip().lower()
    terms = [term for term in query.split() if term]

    choices = []

    for article in _article_map().values():
        article_id = str(article.get("article_id", "")).strip()
        title = str(article.get("title", "")).strip()
        publication = str(
            article.get("publication_name")
            or article.get("publication_group")
            or ""
        ).strip()

        raw_tags = article.get("tags", [])
        if isinstance(raw_tags, list):
            tags = [str(tag) for tag in raw_tags]
        else:
            tags = []

        haystack = " ".join(
            [
                article_id,
                title,
                publication,
                " ".join(tags),
            ]
        ).lower()

        if terms and not all(term in haystack for term in terms):
            continue

        date_value = str(
            article.get("posted_date")
            or article.get("publication_date")
            or ""
        ).strip()

        choices.append(
            {
                "article_id": article_id,
                "title": title,
                "date": date_value,
                "publication_name": publication,
                "tags": tags,
                "inspiring": any(
                    "inspir" in tag.lower()
                    for tag in tags
                ),
            }
        )

    def sort_key(article: dict[str, Any]):
        try:
            numeric_id = int(article["article_id"])
        except (TypeError, ValueError):
            numeric_id = 0

        exact_id = (
            bool(query)
            and article["article_id"].lower() == query
        )

        return (
            exact_id,
            article["date"],
            numeric_id,
        )

    choices.sort(key=sort_key, reverse=True)

    return choices[: max(1, min(limit, 100))]
