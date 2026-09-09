#!/usr/bin/env python3
"""
Build branded static WantToKnow.info PageRecord v1 pages.

This stage writes generated HTML directly into src/site/ at each page's
canonical URL-relative location.

Authoritative inputs
--------------------
src/site/data/corpus/pages-v1.jsonl
src/site/data/elements/headerFooter.json   (loaded dynamically by global.js)
config/schemas/page-v1.schema.json
src/site/assets/css/global.css
src/site/assets/css/pages.css
src/site/assets/js/global.js

Outputs
-------
src/site/<canonical page paths>
src/site/books/index.html
reports/build/static-pages-build.json

Important design rules
----------------------
* Header/footer remain JSON-populated and dynamic. Generated HTML contains only
  the same data-global-header/data-global-footer mount points used by the
  working site.
* No generated page uses a hero area.
* Page content uses a centered reading column.
* The first meaningful Markdown H1 becomes the page's normal document title;
  it is removed from the body to avoid duplication while preserving its locked
  PageRecord anchor ID on the displayed H1.
* Locked navigation anchors are applied exactly and verified against normalized
  heading labels.
* Topic "More Resources" links and /books/index.html are derived at build time.
* Known legacy WantToKnow.info page links are rewritten to their new canonical
  PageRecord paths.
"""

from __future__ import annotations

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any, Iterable, Iterator
from urllib.parse import urljoin, urlparse, urlunparse
import json
import re
import sys

try:
    from markdown_it import MarkdownIt
    from markdown_it.token import Token
except ImportError as exc:
    raise SystemExit(
        "\nMissing dependency: markdown-it-py\n\n"
        "Install it in the wanttoknow-site environment with:\n"
        "  python -m pip install markdown-it-py\n"
    ) from exc


# ============================================================================
# Project paths
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "src" / "site"
OUTPUT_ROOT = SITE

PAGES_FILE = SITE / "data" / "corpus" / "pages-v1.jsonl"
HEADER_FOOTER_FILE = SITE / "data" / "elements" / "headerFooter.json"
SCHEMA_FILE = ROOT / "config" / "schemas" / "page-v1.schema.json"

GLOBAL_CSS_FILE = SITE / "assets" / "css" / "global.css"
PAGES_CSS_FILE = SITE / "assets" / "css" / "pages.css"
GLOBAL_JS_FILE = SITE / "assets" / "js" / "global.js"

BUILD_REPORT = ROOT / "reports" / "build" / "static-pages-build.json"

EXPECTED_SCHEMA_VERSION = 1
EXPECTED_RECORD_TYPE = "page"
SITE_ORIGIN = "https://www.wanttoknow.info"

VALID_SECTIONS = {
    "books",
    "essays",
    "inspiring",
    "poetry",
    "speculation",
    "tech",
    "topics",
}


# Metadata for automatically generated top-level collection indexes.
#
# Any future non-"topics" PageRecord section not listed here still gets an
# index using sensible fallback copy, so the component remains data-driven.
SECTION_INDEX_META = {
    "books": {
        "eyebrow": "WantToKnow.info Library",
        "title": "Books",
        "description": (
            "Explore long-form works and book summaries from the "
            "WantToKnow.info library."
        ),
        "tile_label": "Book",
        "action_label": "Read",
    },
    "essays": {
        "eyebrow": "Long-form perspectives",
        "title": "Essays",
        "description": (
            "Explore essays and extended perspectives from the "
            "WantToKnow.info collection."
        ),
        "tile_label": "Essay",
        "action_label": "Read",
    },
    "inspiring": {
        "eyebrow": "Positive change",
        "title": "Inspiring",
        "description": (
            "Explore inspiring stories, ideas, and resources focused on "
            "positive change and transformation."
        ),
        "tile_label": "Resource",
        "action_label": "Explore",
    },
    "poetry": {
        "eyebrow": "Words + reflection",
        "title": "Poetry",
        "description": (
            "Explore poetry and reflective writing from the "
            "WantToKnow.info collection."
        ),
        "tile_label": "Poetry",
        "action_label": "Read",
    },
    "speculation": {
        "eyebrow": "Exploratory material",
        "title": "Speculation",
        "description": (
            "Explore speculative and exploratory material collected by "
            "WantToKnow.info."
        ),
        "tile_label": "Resource",
        "action_label": "Explore",
    },
    "tech": {
        "eyebrow": "Privacy + Technology",
        "title": "Privacy + Technology",
        "description": (
            "Explore WantToKnow.info resources on privacy, technology, "
            "surveillance, and the digital world."
        ),
        "tile_label": "Resource",
        "action_label": "Explore",
    },
}

GENERATED_INDEX_MARKER = (
    "<!-- GENERATED: build-static-pages.py collection-index -->"
)


# Optional presentation overrides for nested collections. Membership itself is
# inferred from canonical PageRecord paths, not from this configuration.
NESTED_COLLECTION_META = {
    ("speculation", "wingmakers"): {
        "eyebrow": "Exploratory material",
        "title": "WingMakers",
        "description": (
            "Explore the WingMakers material collected and preserved by "
            "WantToKnow.info."
        ),
        "tile_label": "Collection",
        "action_label": "Explore",
    },
}


# ============================================================================
# Markdown
# ============================================================================

MD = MarkdownIt(
    "commonmark",
    {
        "html": True,
        "linkify": False,
        "typographer": False,
    },
)

NAV_EXPLICIT_ID_RE = re.compile(
    r"\s*\{#([A-Za-z0-9_.:-]+)\}\s*$"
)


# ============================================================================
# Generic helpers
# ============================================================================

def e(value: Any) -> str:
    return escape("" if value is None else str(value))


def ea(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise RuntimeError(f"{path} must contain a JSON object.")

    return data


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"{path}: invalid JSONL line {line_number}: {exc}"
                ) from exc

            if not isinstance(record, dict):
                raise RuntimeError(
                    f"{path}: line {line_number} is not a JSON object."
                )

            records.append(record)

    return records


def strip_markdown(text: str) -> str:
    value = text or ""

    value = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"^#{1,6}\s+", "", value, flags=re.MULTILINE)
    value = value.replace("**", "").replace("__", "")
    value = value.replace("*", "").replace("_", "").replace("`", "")
    value = value.replace("&nbsp;", " ").replace("&#160;", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def truncate_text(text: str, limit: int = 260) -> str:
    value = strip_markdown(text)

    if len(value) <= limit:
        return value

    value = value[:limit].rsplit(" ", 1)[0].rstrip()
    return value + "…"


def page_description(page: dict[str, Any], limit: int = 260) -> str:
    summary = page.get("summary_markdown") or ""

    if strip_markdown(summary):
        return truncate_text(summary, limit)

    # Avoid using the Markdown H1 as the page description.
    body = re.sub(
        r"^#\s+.+?$",
        "",
        page.get("content_markdown") or "",
        count=1,
        flags=re.MULTILINE,
    )

    return truncate_text(body, limit)


def canonical_url(path: str) -> str:
    return SITE_ORIGIN + path


def destination_for_path(canonical_path: str) -> Path:
    relative = canonical_path.lstrip("/")
    destination = (OUTPUT_ROOT / relative).resolve()
    output_root = OUTPUT_ROOT.resolve()

    if destination != output_root and output_root not in destination.parents:
        raise RuntimeError(
            f"Refusing to write outside src/site/: {canonical_path!r}"
        )

    return destination


def write_html(canonical_path: str, html: str) -> Path:
    destination = destination_for_path(canonical_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding="utf-8")
    return destination


# ============================================================================
# Locked heading normalization
# ============================================================================

def clean_navigation_heading_label(text: str) -> str:
    """
    MUST remain equivalent to the normalization used when PageRecord v1
    navigation anchors were created.
    """
    value = (text or "").strip()

    value = NAV_EXPLICIT_ID_RE.sub("", value)

    # Markdown images: preserve alt text.
    value = re.sub(
        r"!\[([^\]]*)\]\([^)]+\)",
        r"\1",
        value,
    )

    # Markdown links: preserve visible text.
    value = re.sub(
        r"\[([^\]]+)\]\([^)]+\)",
        r"\1",
        value,
    )

    # Legacy HTML embedded in headings.
    value = re.sub(
        r"<[^>]+>",
        "",
        value,
    )

    value = value.replace("**", "")
    value = value.replace("__", "")
    value = value.replace("*", "")
    value = value.replace("_", "")
    value = value.replace("`", "")

    value = (
        value
        .replace("&nbsp;", " ")
        .replace("&#160;", " ")
    )

    value = re.sub(r"\s+", " ", value)

    return value.strip()


# ============================================================================
# Build-input validation
# ============================================================================

def validate_required_files() -> None:
    required = [
        PAGES_FILE,
        HEADER_FOOTER_FILE,
        SCHEMA_FILE,
        GLOBAL_CSS_FILE,
        PAGES_CSS_FILE,
        GLOBAL_JS_FILE,
    ]

    missing = [
        path
        for path in required
        if not path.exists()
    ]

    if missing:
        lines = "\n".join(f"  {path}" for path in missing)
        raise RuntimeError(
            "Required site files are missing:\n" + lines
        )


def validate_header_footer_contract() -> None:
    """
    The static generator does not render this JSON. global.js fetches it at
    runtime. We still validate the top-level contract so a broken site shell
    is caught before generating 140 pages.
    """
    data = load_json(HEADER_FOOTER_FILE)

    required = {
        "brand",
        "search",
        "topics",
        "menu",
        "social",
        "footer",
    }

    missing = sorted(required - set(data))

    if missing:
        raise RuntimeError(
            "headerFooter.json is missing required keys: "
            + ", ".join(missing)
        )


def validate_build_inputs(pages: list[dict[str, Any]]) -> None:
    validate_required_files()
    validate_header_footer_contract()

    if not pages:
        raise RuntimeError(
            "PageRecord v1 corpus is empty."
        )
        
    ids = [page.get("id") for page in pages]
    paths = [page.get("path") for page in pages]

    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate page IDs in pages-v1.jsonl.")

    if len(paths) != len(set(paths)):
        raise RuntimeError("Duplicate canonical paths in pages-v1.jsonl.")

    for page in pages:
        page_id = page.get("id", "<unknown>")

        if page.get("schema_version") != EXPECTED_SCHEMA_VERSION:
            raise RuntimeError(
                f"{page_id}: unsupported schema_version "
                f"{page.get('schema_version')!r}."
            )

        if page.get("record_type") != EXPECTED_RECORD_TYPE:
            raise RuntimeError(
                f"{page_id}: unexpected record_type "
                f"{page.get('record_type')!r}."
            )

        if page.get("section") not in VALID_SECTIONS:
            raise RuntimeError(
                f"{page_id}: unknown section {page.get('section')!r}."
            )

        if page.get("section") == "topics" and not page.get("topic"):
            raise RuntimeError(
                f"{page_id}: topic page has no structural topic."
            )

        path = page.get("path", "")

        if not path.startswith("/") or not path.endswith(".html"):
            raise RuntimeError(
                f"{page_id}: invalid canonical path {path!r}."
            )


# ============================================================================
# Lookups
# ============================================================================

def build_topic_lookup(
    pages: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for page in pages:
        if page["section"] == "topics" and page.get("topic"):
            lookup[page["topic"]].append(page)

    for topic_pages in lookup.values():
        topic_pages.sort(
            key=lambda item: (
                -(item.get("priority") or 0),
                item["title"].casefold(),
            )
        )

    return dict(lookup)


def sort_navigation_pages(
    pages: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sorted(
        list(pages),
        key=lambda item: (
            -(item.get("priority") or 0),
            item["title"].casefold(),
        ),
    )


def get_section_groups(
    pages: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """
    Group all top-level, non-topic PageRecords by section.

    "topics" is intentionally excluded because /topics/{slug}/ has a separate
    information architecture and may use hand-built landing pages.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for page in pages:
        section = page["section"]

        if section == "topics":
            continue

        groups[section].append(page)

    return {
        section: sort_navigation_pages(section_pages)
        for section, section_pages in groups.items()
        if section_pages
    }


def get_books(
    pages: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    # Backwards-compatible helper used by reports/audits.
    return sort_navigation_pages(
        page
        for page in pages
        if page["section"] == "books"
    )


def page_path_parts(
    page: dict[str, Any],
) -> list[str]:
    return [
        part
        for part in page["path"].strip("/").split("/")
        if part
    ]


def get_nested_collection_slug(
    page: dict[str, Any],
) -> str | None:
    """
    Infer one nested collection level from the canonical path.

    Examples:
      /speculation/foo.html
          -> None

      /speculation/wingmakers/foo.html
          -> "wingmakers"

    Deeper descendants are grouped under their first nested segment so this
    remains stable if a collection later develops subdirectories of its own.
    """
    parts = page_path_parts(page)

    if len(parts) < 3:
        return None

    if parts[0] != page["section"]:
        raise RuntimeError(
            f"{page['id']}: canonical path {page['path']!r} "
            f"does not begin with section {page['section']!r}."
        )

    return parts[1]


def get_nested_collection_groups(
    section_groups: dict[str, list[dict[str, Any]]],
) -> dict[
    str,
    dict[str, list[dict[str, Any]]]
]:
    nested: dict[
        str,
        dict[str, list[dict[str, Any]]]
    ] = {}

    for section, section_pages in section_groups.items():
        section_nested: dict[
            str,
            list[dict[str, Any]]
        ] = defaultdict(list)

        for page in section_pages:
            slug = get_nested_collection_slug(page)

            if slug:
                section_nested[slug].append(page)

        if section_nested:
            nested[section] = {
                slug: sort_navigation_pages(pages)
                for slug, pages
                in section_nested.items()
            }

    return nested


def get_direct_section_pages(
    section: str,
    section_pages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return sort_navigation_pages(
        page
        for page in section_pages
        if get_nested_collection_slug(page) is None
    )


def get_nested_collection_meta(
    section: str,
    slug: str,
) -> dict[str, str]:
    key = (
        section,
        slug,
    )

    if key in NESTED_COLLECTION_META:
        return NESTED_COLLECTION_META[key]

    title = slug.replace("-", " ").title()

    return {
        "eyebrow": get_section_index_meta(section)["title"],
        "title": title,
        "description": (
            f"Explore the {title} collection from WantToKnow.info."
        ),
        "tile_label": "Collection",
        "action_label": "Explore",
    }


def get_section_index_meta(
    section: str,
) -> dict[str, str]:
    if section in SECTION_INDEX_META:
        return SECTION_INDEX_META[section]

    title = section.replace("-", " ").title()

    return {
        "eyebrow": "WantToKnow.info",
        "title": title,
        "description": (
            f"Explore {title.lower()} resources from the "
            "WantToKnow.info collection."
        ),
        "tile_label": "Resource",
        "action_label": "Explore",
    }


def section_display_name(page: dict[str, Any]) -> str:
    if page["section"] == "topics":
        return (page.get("topic") or "Topic").replace("-", " ").title()

    labels = {
        "books": "Books",
        "essays": "Essays",
        "inspiring": "Inspiring",
        "poetry": "Poetry",
        "speculation": "Speculation",
        "tech": "Privacy + Technology",
    }

    return labels.get(
        page["section"],
        page["section"].replace("-", " ").title(),
    )


# ============================================================================
# Legacy/internal-link rewriting
# ============================================================================

def normalize_site_host(host: str) -> str:
    value = (host or "").lower()
    return value[4:] if value.startswith("www.") else value


def normalize_path(path: str) -> str:
    value = path or "/"

    if not value.startswith("/"):
        value = "/" + value

    # Preserve root; remove duplicate trailing slash elsewhere for matching.
    if value != "/":
        value = value.rstrip("/")

    return value


def build_legacy_link_map(
    pages: Iterable[dict[str, Any]],
) -> dict[str, str]:
    """
    Build aliases for canonicalization of links inside migrated Markdown.

    Keys include:
      * full legacy URLs
      * legacy URL paths
      * redirect source paths
      * canonical paths
    """
    mapping: dict[str, str] = {}

    for page in pages:
        target = page["path"]

        mapping[normalize_path(target)] = target

        for legacy_url in page.get("legacy_urls", []):
            parsed = urlparse(legacy_url)

            if normalize_site_host(parsed.netloc) == "wanttoknow.info":
                mapping[
                    normalize_path(parsed.path)
                ] = target

            mapping[
                legacy_url.rstrip("/")
            ] = target

        for redirect in page.get("redirects", []):
            source = redirect.get("from")

            if source:
                mapping[
                    normalize_path(source)
                ] = target

    return mapping


def rewrite_internal_href(
    href: str,
    page: dict[str, Any],
    legacy_map: dict[str, str],
) -> str:
    """
    Rewrite ONLY known migrated WantToKnow links to PageRecord v1 paths.

    If a WTK link is not represented by the 139-page migration corpus, keep a
    working absolute legacy/live WantToKnow URL instead of fabricating a local
    path that does not exist in the new tree yet.
    """
    if not href:
        return href

    value = href.strip()

    if (
        value.startswith("#")
        or value.startswith("mailto:")
        or value.startswith("tel:")
        or value.startswith("javascript:")
        or value.startswith("data:")
    ):
        return value

    source_url = (
        page.get("source", {}).get("legacy_url")
        or (page.get("legacy_urls") or [""])[0]
        or canonical_url(page["path"])
    )

    parsed = urlparse(value)

    # Resolve relative links against the original legacy page location because
    # migrated pages may now live in a different directory.
    if not parsed.scheme and not value.startswith("//"):
        resolved = urlparse(urljoin(source_url, value))
    else:
        resolved = parsed

    # Ordinary external link: preserve exactly as authored.
    if (
        resolved.scheme in {"http", "https"}
        and normalize_site_host(resolved.netloc) != "wanttoknow.info"
    ):
        return value

    path_key = normalize_path(resolved.path)

    target = (
        legacy_map.get(value.rstrip("/"))
        or legacy_map.get(path_key)
    )

    # We KNOW this page was migrated: use its new canonical path.
    if target:
        result = target

        if resolved.query:
            result += "?" + resolved.query

        if resolved.fragment:
            result += "#" + resolved.fragment

        return result

    # Internal WTK destination not yet represented in PageRecord v1:
    # preserve a working absolute WTK URL for this migration stage.
    if (
        normalize_site_host(resolved.netloc) == "wanttoknow.info"
        or value.startswith("/")
        or (
            not parsed.scheme
            and not value.startswith("//")
        )
    ):
        result = SITE_ORIGIN + (resolved.path or "/")

        if resolved.query:
            result += "?" + resolved.query

        if resolved.fragment:
            result += "#" + resolved.fragment

        return result

    return value


def rewrite_relative_asset_src(
    src: str,
    page: dict[str, Any],
) -> str:
    """
    Resolve only relative image/media paths against the original legacy page.
    Absolute/root-relative/external sources remain untouched.
    """
    if not src:
        return src

    value = src.strip()
    parsed = urlparse(value)

    if (
        parsed.scheme
        or value.startswith("/")
        or value.startswith("//")
        or value.startswith("data:")
    ):
        return value

    source_url = (
        page.get("source", {}).get("legacy_url")
        or (page.get("legacy_urls") or [""])[0]
        or canonical_url(page["path"])
    )

    resolved = urlparse(urljoin(source_url, value))

    if normalize_site_host(resolved.netloc) == "wanttoknow.info":
        result = resolved.path

        if resolved.query:
            result += "?" + resolved.query

        if resolved.fragment:
            result += "#" + resolved.fragment

        return result

    return value


def walk_tokens(tokens: Iterable[Token]) -> Iterator[Token]:
    for token in tokens:
        yield token

        if token.children:
            yield from walk_tokens(token.children)


def rewrite_body_urls(
    tokens: list[Token],
    page: dict[str, Any],
    legacy_map: dict[str, str],
) -> None:
    for token in walk_tokens(tokens):
        if token.type == "link_open":
            href = token.attrGet("href")

            if href is not None:
                token.attrSet(
                    "href",
                    rewrite_internal_href(
                        href,
                        page,
                        legacy_map,
                    ),
                )

        elif token.type == "image":
            src = token.attrGet("src")

            if src is not None:
                token.attrSet(
                    "src",
                    rewrite_relative_asset_src(
                        src,
                        page,
                    ),
                )


# ============================================================================
# Markdown body + locked anchors
# ============================================================================

def render_markdown_body(
    page: dict[str, Any],
    legacy_map: dict[str, str],
) -> tuple[str, dict[str, Any]]:
    """
    Apply locked anchors and move the first meaningful H1 into the ordinary
    document heading area (not a hero).
    """
    tokens = MD.parse(page["content_markdown"])
    anchors = page["page_navigation"]["anchors"]

    output_tokens: list[Token] = []
    anchor_position = 0
    title_heading: dict[str, Any] | None = None

    i = 0

    while i < len(tokens):
        token = tokens[i]

        if token.type != "heading_open":
            output_tokens.append(token)
            i += 1
            continue

        inline = tokens[i + 1] if i + 1 < len(tokens) else None
        close = tokens[i + 2] if i + 2 < len(tokens) else None

        if (
            inline is None
            or inline.type != "inline"
            or close is None
            or close.type != "heading_close"
        ):
            raise RuntimeError(
                f"{page['path']}: unexpected Markdown heading token structure."
            )

        raw_label = inline.content.strip()
        normalized_label = clean_navigation_heading_label(raw_label)

        # Remove meaningless/decorative legacy headings entirely.
        if not normalized_label:
            i += 3
            continue

        if anchor_position >= len(anchors):
            raise RuntimeError(
                f"{page['path']}: more meaningful Markdown headings than "
                "locked PageRecord anchors."
            )

        anchor = anchors[anchor_position]

        if normalized_label != anchor["label"]:
            raise RuntimeError(
                f"{page['path']}: heading/anchor label mismatch at "
                f"heading {anchor_position + 1}: "
                f"Markdown={normalized_label!r}, "
                f"PageRecord={anchor['label']!r}"
            )

        anchor_position += 1
        token.attrSet("id", anchor["id"])

        # PageRecord v1 contains one page-title H1. Move it into the ordinary
        # centered document heading so it is not duplicated in the prose body.
        if title_heading is None and token.tag == "h1":
            title_heading = {
                "id": anchor["id"],
                "label": anchor["label"],
                "level": anchor["level"],
            }

            i += 3
            continue

        output_tokens.extend((token, inline, close))
        i += 3

    if anchor_position != len(anchors):
        raise RuntimeError(
            f"{page['path']}: heading/anchor mismatch: consumed "
            f"{anchor_position}, expected {len(anchors)}."
        )

    if title_heading is None:
        raise RuntimeError(
            f"{page['path']}: no meaningful H1 is available for the page title."
        )

    rewrite_body_urls(
        output_tokens,
        page,
        legacy_map,
    )

    html = MD.renderer.render(
        output_tokens,
        MD.options,
        {},
    )

    return html, title_heading


# ============================================================================
# Page components
# ============================================================================

def render_page_heading(
    page: dict[str, Any],
    title_heading: dict[str, Any],
) -> str:
    return f"""
<header class="page-document__header">
  <p class="eyebrow">
    {e(section_display_name(page))}
  </p>

  <h1
    class="page-document__title"
    id="{ea(title_heading['id'])}"
  >
    {e(page['title'])}
  </h1>
</header>
""".strip()


def render_toc(page: dict[str, Any]) -> str:
    navigation = page["page_navigation"]

    if navigation["mode"] != "toc":
        return ""

    anchors = [
        anchor
        for anchor in navigation["anchors"]
        if anchor["toc"] is True
    ]

    if not anchors:
        raise RuntimeError(
            f"{page['path']}: mode='toc' but no toc=true anchors exist."
        )

    min_level = min(anchor["level"] for anchor in anchors)

    items = []

    for anchor in anchors:
        depth = anchor["level"] - min_level

        items.append(
            f"""
<li
  class="page-toc__item"
  data-toc-depth="{depth}"
>
  <a
    class="page-toc__link"
    href="#{ea(anchor['id'])}"
  >
    {e(anchor['label'])}
  </a>
</li>
"""
        )

    return f"""
<nav
  class="page-toc"
  aria-labelledby="page-toc-heading"
>
  <div
    class="page-toc__heading"
    id="page-toc-heading"
  >
    On this page
  </div>

  <ol class="page-toc__list">
    {''.join(items)}
  </ol>
</nav>
""".strip()


def render_more_resources(
    page: dict[str, Any],
    topic_lookup: dict[str, list[dict[str, Any]]],
) -> str:
    if page["section"] != "topics" or not page.get("topic"):
        return ""

    resources = [
        other
        for other in topic_lookup.get(page["topic"], [])
        if other["id"] != page["id"]
    ]

    if not resources:
        return ""

    pills = "".join(
        f"""
<a
  class="resource-pill"
  href="{ea(resource['path'])}"
>
  {e(resource['title'])}
</a>
"""
        for resource in resources
    )

    return f"""
<section
  class="more-resources"
  aria-labelledby="more-resources-heading"
>
  <div class="page-reading-column">
    <p class="eyebrow">
      Explore this topic
    </p>

    <h2
      class="more-resources__heading"
      id="more-resources-heading"
    >
      More Resources
    </h2>

    <div class="resource-pill-list">
      {pills}
    </div>
  </div>
</section>
""".strip()


def render_page_content(
    page: dict[str, Any],
    topic_lookup: dict[str, list[dict[str, Any]]],
    legacy_map: dict[str, str],
) -> str:
    body_html, title_heading = render_markdown_body(
        page,
        legacy_map,
    )

    heading_html = render_page_heading(
        page,
        title_heading,
    )

    toc_html = render_toc(page)
    resources_html = render_more_resources(
        page,
        topic_lookup,
    )

    classes = ["page-document"]

    if page["section"] == "books":
        classes.append("page-document--book")

    if toc_html:
        classes.append("page-document--has-toc")

    return f"""
<article
  class="{' '.join(classes)}"
  data-page-id="{ea(page['id'])}"
  data-section="{ea(page['section'])}"
  data-topic="{ea(page.get('topic') or '')}"
>
  <div class="container">
    <div class="page-reading-column">
      {heading_html}

      {toc_html}

      <div class="page-content">
        {body_html}
      </div>
    </div>
  </div>

  {resources_html}
</article>
""".strip()


# ============================================================================
# Reusable collection navigation
# ============================================================================

def render_collection_tile(
    *,
    href: str,
    title: str,
    description: str,
    eyebrow: str,
    action_label: str,
    authors: list[str] | None = None,
    extra_class: str = "",
) -> str:
    """
    Generic reusable navigation tile.

    Both individual PageRecords and nested collection indexes use this exact
    component, so parent and child navigation stay visually consistent.
    """
    classes = ["collection-tile"]

    if extra_class:
        classes.append(extra_class)

    author_html = ""

    if authors:
        author_html = f"""
<p class="collection-tile__author">
  {e(', '.join(authors))}
</p>
"""

    description_html = ""

    if description:
        description_html = f"""
<p class="collection-tile__description">
  {e(description)}
</p>
"""

    return f"""
<a
  class="{' '.join(classes)}"
  href="{ea(href)}"
>
  <div class="collection-tile__body">
    <p class="collection-tile__eyebrow">
      {e(eyebrow)}
    </p>

    <h2 class="collection-tile__title">
      {e(title)}
    </h2>

    {author_html}
    {description_html}
  </div>

  <span class="collection-tile__link">
    {e(action_label)}
    <span aria-hidden="true">→</span>
  </span>
</a>
""".strip()


def render_navigation_tile(
    page: dict[str, Any],
    *,
    tile_label: str,
    action_label: str,
) -> str:
    return render_collection_tile(
        href=page["path"],
        title=page["title"],
        description=page_description(
            page,
            limit=210,
        ),
        eyebrow=tile_label,
        action_label=action_label,
        authors=page.get("authors") or [],
    )


def render_nested_collection_tile(
    *,
    section: str,
    slug: str,
    pages: list[dict[str, Any]],
) -> str:
    meta = get_nested_collection_meta(
        section,
        slug,
    )

    href = f"/{section}/{slug}/"

    count = len(pages)

    count_text = (
        "1 page"
        if count == 1
        else f"{count} pages"
    )

    description = (
        meta["description"].rstrip()
        + f" {count_text}."
    )

    return render_collection_tile(
        href=href,
        title=meta["title"],
        description=description,
        eyebrow=meta["tile_label"],
        action_label=meta["action_label"],
        extra_class="collection-tile--collection",
    )


def render_navigation_section(
    pages: list[dict[str, Any]],
    *,
    section: str,
    eyebrow: str,
    title: str,
    description: str,
    tile_label: str,
    action_label: str,
    nested_collections: dict[
        str,
        list[dict[str, Any]]
    ] | None = None,
) -> str:
    """
    Reusable collection navigation section.

    At a top-level section index, nested collections appear as ONE tile each
    while direct pages appear as normal page tiles.

    At a nested collection index, pass only its pages and no nested_collections.
    """
    nested_collections = (
        nested_collections
        or {}
    )

    tiles: list[str] = []

    # Put collection/group tiles first because they are higher-level navigation.
    for slug, nested_pages in sorted(
        nested_collections.items(),
        key=lambda item:
            get_nested_collection_meta(
                section,
                item[0],
            )["title"].casefold(),
    ):
        tiles.append(
            render_nested_collection_tile(
                section=section,
                slug=slug,
                pages=nested_pages,
            )
        )

    for page in pages:
        tiles.append(
            render_navigation_tile(
                page,
                tile_label=tile_label,
                action_label=action_label,
            )
        )

    heading_id = (
        "collection-index-"
        + re.sub(
            r"[^a-z0-9-]+",
            "-",
            f"{section}-{title}".lower(),
        ).strip("-")
        + "-title"
    )

    return f"""
{GENERATED_INDEX_MARKER}
<section
  class="collection-index"
  data-collection-section="{ea(section)}"
  aria-labelledby="{ea(heading_id)}"
>
  <div class="container">
    <div class="collection-index__inner">

      <header class="collection-index__intro">
        <p class="eyebrow">
          {e(eyebrow)}
        </p>

        <h1
          class="collection-index__title"
          id="{ea(heading_id)}"
        >
          {e(title)}
        </h1>

        <p class="collection-index__lede">
          {e(description)}
        </p>
      </header>

      <div class="collection-grid">
        {''.join(tiles)}
      </div>

    </div>
  </div>
</section>
""".strip()


def render_section_index_content(
    section: str,
    direct_pages: list[dict[str, Any]],
    nested_collections: dict[
        str,
        list[dict[str, Any]]
    ] | None = None,
) -> str:
    meta = get_section_index_meta(
        section
    )

    return render_navigation_section(
        direct_pages,
        section=section,
        eyebrow=meta["eyebrow"],
        title=meta["title"],
        description=meta["description"],
        tile_label=meta["tile_label"],
        action_label=meta["action_label"],
        nested_collections=nested_collections,
    )


def render_nested_index_content(
    section: str,
    slug: str,
    pages: list[dict[str, Any]],
) -> str:
    meta = get_nested_collection_meta(
        section,
        slug,
    )

    parent_meta = get_section_index_meta(
        section
    )

    return render_navigation_section(
        pages,
        section=f"{section}-{slug}",
        eyebrow=meta["eyebrow"],
        title=meta["title"],
        description=meta["description"],
        tile_label=parent_meta["tile_label"],
        action_label=parent_meta["action_label"],
    )


# ============================================================================
# Metadata/document shell
# ============================================================================

def render_json_ld(
    *,
    title: str,
    url: str,
    description: str,
    page_type: str = "WebPage",
) -> str:
    graph = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{SITE_ORIGIN}/#organization",
                "name": "WantToKnow.info",
                "url": f"{SITE_ORIGIN}/",
                "logo": {
                    "@type": "ImageObject",
                    "url": f"{SITE_ORIGIN}/assets/brand/wtk-logo.png",
                },
            },
            {
                "@type": "WebSite",
                "@id": f"{SITE_ORIGIN}/#website",
                "url": f"{SITE_ORIGIN}/",
                "name": "WantToKnow.info",
                "publisher": {
                    "@id": f"{SITE_ORIGIN}/#organization",
                },
                "inLanguage": "en-US",
            },
            {
                "@type": page_type,
                "@id": f"{url}#webpage",
                "url": url,
                "name": title,
                "description": description,
                "isPartOf": {
                    "@id": f"{SITE_ORIGIN}/#website",
                },
                "about": {
                    "@id": f"{SITE_ORIGIN}/#organization",
                },
                "inLanguage": "en-US",
            },
        ],
    }

    return json.dumps(
        graph,
        ensure_ascii=False,
        separators=(",", ":"),
    ).replace("</", "<\\/")


def render_document(
    *,
    title: str,
    body: str,
    canonical_path: str,
    description: str,
    body_class: str,
    structured_page_type: str = "WebPage",
) -> str:
    full_title = f"{title} | WantToKnow.info"
    url = canonical_url(canonical_path)
    share_image = (
        f"{SITE_ORIGIN}/assets/social/"
        "wtk-home-share-1200x630.jpg"
    )

    json_ld = render_json_ld(
        title=title,
        url=url,
        description=description,
        page_type=structured_page_type,
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#7658f6">
  <meta name="color-scheme" content="light">

  <title>{e(full_title)}</title>

  <meta
    name="description"
    content="{ea(description)}"
  >

  <meta
    name="robots"
    content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
  >

  <link
    rel="canonical"
    href="{ea(url)}"
  >

  <meta property="og:type" content="website">
  <meta property="og:site_name" content="WantToKnow.info">
  <meta property="og:locale" content="en_US">
  <meta property="og:url" content="{ea(url)}">
  <meta property="og:title" content="{ea(full_title)}">
  <meta property="og:description" content="{ea(description)}">
  <meta property="og:image" content="{ea(share_image)}">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta
    property="og:image:alt"
    content="WantToKnow.info — verifiable information and inspiring solutions"
  >

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{ea(full_title)}">
  <meta name="twitter:description" content="{ea(description)}">
  <meta name="twitter:image" content="{ea(share_image)}">

  <meta name="application-name" content="WantToKnow.info">
  <meta name="apple-mobile-web-app-title" content="WantToKnow.info">

  <link
    rel="alternate"
    type="application/rss+xml"
    title="WTK Conscious Media"
    href="https://wtkconsciousmedia.substack.com/feed"
  >

  <link
    rel="icon"
    type="image/x-icon"
    href="/assets/images/favicon.ico"
  >

  <link
    rel="icon"
    type="image/png"
    sizes="32x32"
    href="/assets/images/favicon-32x32.png"
  >

  <link
    rel="icon"
    type="image/png"
    sizes="16x16"
    href="/assets/images/favicon-16x16.png"
  >

  <link
    rel="apple-touch-icon"
    sizes="180x180"
    href="/assets/images/apple-touch-icon.png"
  >

  <link rel="manifest" href="/site.webmanifest">

  <script type="application/ld+json">
    {json_ld}
  </script>

  <link rel="stylesheet" href="/assets/css/global.css">
  <link rel="stylesheet" href="/assets/css/pages.css">
</head>

<body class="{ea(body_class)}">
  <a class="skip-link" href="#main-content">
    Skip to main content
  </a>

  <div
    id="global-header"
    data-global-header
  ></div>

  <main id="main-content">
    {body}
  </main>

  <div
    id="global-footer"
    data-global-footer
  ></div>

  <script
    src="/assets/js/global.js"
    defer
  ></script>
</body>
</html>
"""


# ============================================================================
# Build orchestration
# ============================================================================

def build_pages(
    pages: list[dict[str, Any]],
    topic_lookup: dict[str, list[dict[str, Any]]],
    legacy_map: dict[str, str],
) -> list[str]:
    built: list[str] = []

    for page in pages:
        body = render_page_content(
            page,
            topic_lookup,
            legacy_map,
        )

        description = page_description(
            page,
            limit=300,
        )

        html = render_document(
            title=page["title"],
            body=body,
            canonical_path=page["path"],
            description=description,
            body_class=(
                f"page-record "
                f"page-section-{page['section']}"
            ),
            structured_page_type=(
                "WebPage"
                if page["section"] != "books"
                else "WebPage"
            ),
        )

        destination = write_html(
            page["path"],
            html,
        )

        built.append(
            str(
                destination.relative_to(ROOT)
            )
        )

    return built


def can_overwrite_collection_index(
    destination: Path,
    section: str,
) -> bool:
    """
    Preserve hand-built index pages.

    /books/index.html is already owned by this generator from the previous
    migration stage, so it may always be replaced. Other existing index pages
    are replaced only if they carry our generated marker.
    """
    if not destination.exists():
        return True

    if section == "books":
        return True

    try:
        existing = destination.read_text(
            encoding="utf-8"
        )
    except UnicodeDecodeError:
        return False

    return GENERATED_INDEX_MARKER in existing


def build_section_indexes(
    section_groups: dict[str, list[dict[str, Any]]],
    nested_groups: dict[
        str,
        dict[str, list[dict[str, Any]]]
    ],
) -> dict[str, Any]:
    generated: dict[str, str] = {}
    preserved: dict[str, str] = {}
    nested_generated: dict[str, str] = {}
    nested_preserved: dict[str, str] = {}

    for section, section_pages in sorted(
        section_groups.items()
    ):
        meta = get_section_index_meta(
            section
        )

        section_nested = nested_groups.get(
            section,
            {},
        )

        direct_pages = get_direct_section_pages(
            section,
            section_pages,
        )

        # ------------------------------------------------------------
        # Parent/top-level collection index
        # ------------------------------------------------------------

        output_path = (
            f"/{section}/index.html"
        )

        canonical_path = (
            f"/{section}/"
        )

        destination = (
            destination_for_path(
                output_path
            )
        )

        if can_overwrite_collection_index(
            destination,
            section,
        ):
            body = render_section_index_content(
                section,
                direct_pages,
                section_nested,
            )

            html = render_document(
                title=meta["title"],
                body=body,
                canonical_path=canonical_path,
                description=meta["description"],
                body_class=(
                    "page-collection-index "
                    f"page-section-{section}"
                ),
                structured_page_type="CollectionPage",
            )

            destination = write_html(
                output_path,
                html,
            )

            generated[section] = str(
                destination.relative_to(
                    ROOT
                )
            )

        else:
            preserved[section] = str(
                destination.relative_to(
                    ROOT
                )
            )

        # ------------------------------------------------------------
        # Nested collection indexes
        # ------------------------------------------------------------

        for slug, nested_pages in sorted(
            section_nested.items()
        ):
            nested_key = (
                f"{section}/{slug}"
            )

            nested_output_path = (
                f"/{section}/{slug}/index.html"
            )

            nested_canonical_path = (
                f"/{section}/{slug}/"
            )

            nested_destination = (
                destination_for_path(
                    nested_output_path
                )
            )

            nested_meta = (
                get_nested_collection_meta(
                    section,
                    slug,
                )
            )

            if not can_overwrite_collection_index(
                nested_destination,
                nested_key,
            ):
                nested_preserved[
                    nested_key
                ] = str(
                    nested_destination.relative_to(
                        ROOT
                    )
                )
                continue

            nested_body = (
                render_nested_index_content(
                    section,
                    slug,
                    nested_pages,
                )
            )

            nested_html = render_document(
                title=nested_meta["title"],
                body=nested_body,
                canonical_path=(
                    nested_canonical_path
                ),
                description=(
                    nested_meta["description"]
                ),
                body_class=(
                    "page-collection-index "
                    f"page-section-{section} "
                    "page-nested-collection "
                    f"page-collection-{slug}"
                ),
                structured_page_type=(
                    "CollectionPage"
                ),
            )

            nested_destination = write_html(
                nested_output_path,
                nested_html,
            )

            nested_generated[
                nested_key
            ] = str(
                nested_destination.relative_to(
                    ROOT
                )
            )

    return {
        "generated":
            generated,
        "preserved_existing":
            preserved,
        "nested_generated":
            nested_generated,
        "nested_preserved_existing":
            nested_preserved,
    }


def audit_generated_navigation(
    pages: list[dict[str, Any]],
    topic_lookup: dict[str, list[dict[str, Any]]],
    section_groups: dict[str, list[dict[str, Any]]],
    nested_groups: dict[
        str,
        dict[str, list[dict[str, Any]]]
    ],
) -> dict[str, Any]:
    """
    Validate generator-owned navigation:
      * direct page tiles
      * parent -> nested collection tiles
      * nested collection -> page tiles
      * More Resources links
    """
    file_targets: list[
        tuple[str, str]
    ] = []

    index_targets: list[
        tuple[str, str]
    ] = []

    for section, section_pages in section_groups.items():
        section_nested = nested_groups.get(
            section,
            {},
        )

        direct_pages = get_direct_section_pages(
            section,
            section_pages,
        )

        for page in direct_pages:
            file_targets.append(
                (
                    f"collection-tile:{section}",
                    page["path"],
                )
            )

        for slug, nested_pages in section_nested.items():
            index_targets.append(
                (
                    f"nested-collection:{section}",
                    f"/{section}/{slug}/index.html",
                )
            )

            for page in nested_pages:
                file_targets.append(
                    (
                        f"nested-tile:{section}/{slug}",
                        page["path"],
                    )
                )

    for page in pages:
        if (
            page["section"] != "topics"
            or not page.get("topic")
        ):
            continue

        for other in topic_lookup.get(
            page["topic"],
            [],
        ):
            if other["id"] == page["id"]:
                continue

            file_targets.append(
                (
                    "more-resources",
                    other["path"],
                )
            )

    broken = []

    for kind, target in (
        file_targets
        + index_targets
    ):
        destination = (
            destination_for_path(
                target
            )
        )

        if not destination.exists():
            broken.append({
                "kind":
                    kind,
                "href":
                    (
                        target[:-10]
                        if target.endswith(
                            "/index.html"
                        )
                        else target
                    ),
                "expected_file":
                    str(
                        destination.relative_to(
                            ROOT
                        )
                    ),
            })

    return {
        "generated_navigation_links_checked":
            len(file_targets)
            + len(index_targets),
        "broken_generated_navigation_links":
            broken,
        "broken_generated_navigation_count":
            len(broken),
    }


def audit_outputs(
    pages: list[dict[str, Any]],
    section_index_result: dict[str, Any],
) -> dict[str, Any]:
    missing: list[str] = []

    for page in pages:
        destination = destination_for_path(
            page["path"]
        )

        if not destination.exists():
            missing.append(
                page["path"]
            )

    generated_indexes = (
        section_index_result[
            "generated"
        ]
    )

    nested_generated_indexes = (
        section_index_result[
            "nested_generated"
        ]
    )

    for section, relative_path in generated_indexes.items():
        destination = ROOT / relative_path

        if not destination.exists():
            missing.append(
                f"/{section}/index.html"
            )

    for nested_key, relative_path in nested_generated_indexes.items():
        destination = ROOT / relative_path

        if not destination.exists():
            missing.append(
                f"/{nested_key}/index.html"
            )

    return {
        "expected_generated_html_files":
            len(pages)
            + len(generated_indexes)
            + len(nested_generated_indexes),
        "missing_generated_files":
            missing,
        "missing_generated_count":
            len(missing),
    }


def write_build_report(
    report: dict[str, Any],
) -> None:
    BUILD_REPORT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    BUILD_REPORT.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    pages = load_jsonl(
        PAGES_FILE
    )

    validate_build_inputs(
        pages
    )

    topic_lookup = (
        build_topic_lookup(
            pages
        )
    )

    section_groups = (
        get_section_groups(
            pages
        )
    )

    nested_groups = (
        get_nested_collection_groups(
            section_groups
        )
    )

    legacy_map = (
        build_legacy_link_map(
            pages
        )
    )

    built_pages = build_pages(
        pages,
        topic_lookup,
        legacy_map,
    )

    section_index_result = (
        build_section_indexes(
            section_groups,
            nested_groups,
        )
    )

    audit = audit_outputs(
        pages,
        section_index_result,
    )

    navigation_audit = audit_generated_navigation(
        pages,
        topic_lookup,
        section_groups,
        nested_groups,
    )

    if audit[
        "missing_generated_count"
    ]:
        raise RuntimeError(
            "Generated-file audit failed: "
            + ", ".join(
                audit[
                    "missing_generated_files"
                ]
            )
        )

    if navigation_audit[
        "broken_generated_navigation_count"
    ]:
        raise RuntimeError(
            "Generated-navigation audit failed: "
            + json.dumps(
                navigation_audit[
                    "broken_generated_navigation_links"
                ][:20],
                ensure_ascii=False,
            )
        )

    toc_pages = sum(
        page[
            "page_navigation"
        ]["mode"] == "toc"
        for page in pages
    )

    heading_anchors = sum(
        len(
            page[
                "page_navigation"
            ]["anchors"]
        )
        for page in pages
    )

    more_resources_links = sum(
        max(
            0,
            len(
                topic_lookup.get(
                    page.get("topic"),
                    [],
                )
            ) - 1,
        )
        for page in pages
        if page["section"] == "topics"
    )

    report = {
        "build_type":
            "static-pages",
        "page_schema_version":
            EXPECTED_SCHEMA_VERSION,
        "source_corpus":
            str(
                PAGES_FILE.relative_to(
                    ROOT
                )
            ),
        "output_root":
            str(
                OUTPUT_ROOT.relative_to(
                    ROOT
                )
            ),
        "dynamic_header_footer":
            True,
        "header_footer_source":
            "/data/elements/headerFooter.json",
        "global_script":
            "/assets/js/global.js",
        "pages_stylesheet":
            "/assets/css/pages.css",
        "pages_built":
            len(built_pages),
        "section_counts": {
            section: len(section_pages)
            for section, section_pages
            in sorted(section_groups.items())
        },
        "collection_indexes_generated":
            section_index_result["generated"],
        "collection_indexes_preserved":
            section_index_result["preserved_existing"],

        "nested_collections": {
            section: {
                slug: len(nested_pages)
                for slug, nested_pages
                in sorted(collections.items())
            }
            for section, collections
            in sorted(nested_groups.items())
        },
        "nested_collection_indexes_generated":
            section_index_result["nested_generated"],
        "nested_collection_indexes_preserved":
            section_index_result["nested_preserved_existing"],
        "topic_groups":
            len(topic_lookup),
        "topic_pages":
            sum(
                page["section"]
                == "topics"
                for page in pages
            ),
        "toc_pages":
            toc_pages,
        "heading_anchors":
            heading_anchors,
        "more_resources_links_rendered":
            more_resources_links,
        "known_legacy_link_aliases":
            len(legacy_map),
        **audit,
        **navigation_audit,
    }

    write_build_report(
        report
    )

    print()
    print(
        "======================================"
    )
    print(
        "STATIC PAGE BUILD"
    )
    print(
        "======================================"
    )

    print(
        f"Pages built:             "
        f"{len(built_pages):,}"
    )

    print(
        f"Collection indexes:      "
        f"{len(section_index_result['generated']):,}"
    )

    print(
        f"Existing indexes kept:   "
        f"{len(section_index_result['preserved_existing']):,}"
    )

    print(
        f"Nested collections:      "
        f"{sum(len(v) for v in nested_groups.values()):,}"
    )

    print(
        f"Nested indexes built:    "
        f"{len(section_index_result['nested_generated']):,}"
    )

    print(
        f"Topic groups:            "
        f"{len(topic_lookup):,}"
    )

    print(
        f"TOC pages:               "
        f"{toc_pages:,}"
    )

    print(
        f"Heading anchors:         "
        f"{heading_anchors:,}"
    )

    print(
        f"More Resources links:    "
        f"{more_resources_links:,}"
    )

    print(
        f"Legacy link aliases:     "
        f"{len(legacy_map):,}"
    )

    print(
        f"Generated files missing: "
        f"{audit['missing_generated_count']:,}"
    )

    print(
        f"Generated links checked: "
        f"{navigation_audit['generated_navigation_links_checked']:,}"
    )

    print(
        f"Broken generated links:  "
        f"{navigation_audit['broken_generated_navigation_count']:,}"
    )

    print()
    if section_index_result["generated"]:
        print()
        print("Generated collection indexes:")

        for section, path in sorted(
            section_index_result[
                "generated"
            ].items()
        ):
            print(
                f"  {section:<18} {path}"
            )

    if section_index_result[
        "nested_generated"
    ]:
        print()
        print("Generated nested collection indexes:")

        for nested_key, path in sorted(
            section_index_result[
                "nested_generated"
            ].items()
        ):
            print(
                f"  {nested_key:<24} {path}"
            )

    if section_index_result[
        "preserved_existing"
    ]:
        print()
        print("Preserved hand-built indexes:")

        for section, path in sorted(
            section_index_result[
                "preserved_existing"
            ].items()
        ):
            print(
                f"  {section:<18} {path}"
            )

    if section_index_result[
        "nested_preserved_existing"
    ]:
        print()
        print("Preserved nested hand-built indexes:")

        for nested_key, path in sorted(
            section_index_result[
                "nested_preserved_existing"
            ].items()
        ):
            print(
                f"  {nested_key:<24} {path}"
            )

    print(
        f"Build report:            "
        f"{BUILD_REPORT}"
    )

    print(
        f"Output root:             "
        f"{OUTPUT_ROOT}"
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print()
        print(
            "STATIC PAGE BUILD FAILED",
            file=sys.stderr,
        )
        print(
            str(exc),
            file=sys.stderr,
        )
        raise
