#!/usr/bin/env python3

from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
import re
import xml.etree.ElementTree as ET


ROOT = Path("/srv/wanttoknow/site")
SITE = ROOT / "src/site"

CANONICAL_ORIGIN = "https://www.wanttoknow.info"

REQUIRED_FILES = [
    SITE / "robots.txt",
    SITE / "sitemap.xml",
    SITE / "llms.txt",
    SITE / "assets/social/wtk-home-share-1200x630.jpg",
    SITE / "assets/brand/wtk-logo.png",
]


class HeadParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_head = False
        self.in_title = False
        self.title_parts = []
        self.meta = {}
        self.links = []
        self.jsonld = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        tag = tag.lower()

        if tag == "head":
            self.in_head = True
            return

        if not self.in_head:
            return

        if tag == "title":
            self.in_title = True

        elif tag == "meta":
            key = (
                attrs.get("name")
                or attrs.get("property")
            )
            if key:
                self.meta[key.lower()] = attrs.get(
                    "content", ""
                ).strip()

        elif tag == "link":
            rel = attrs.get("rel", "").lower()
            href = attrs.get("href", "").strip()

            if "canonical" in rel:
                self.links.append(href)

        elif tag == "script":
            if (
                attrs.get("type", "").lower()
                == "application/ld+json"
            ):
                self.jsonld += 1

    def handle_endtag(self, tag):
        tag = tag.lower()

        if tag == "title":
            self.in_title = False

        elif tag == "head":
            self.in_head = False

    def handle_data(self, data):
        if self.in_head and self.in_title:
            self.title_parts.append(data)

    @property
    def title(self):
        return " ".join(
            "".join(self.title_parts).split()
        ).strip()


def public_html_files():
    for path in SITE.rglob("*.html"):
        rel = path.relative_to(SITE)

        if rel.parts and rel.parts[0] == "data":
            continue

        name = path.name.lower()

        if ".bak" in name:
            continue

        if ".pre-" in name:
            continue

        yield path


def parse_page(path):
    text = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    parser = HeadParser()
    parser.feed(text)

    return text, parser


def main():
    issues = []
    canonicals = defaultdict(list)
    indexable_urls = set()

    public_count = 0
    indexable_count = 0
    noindex_count = 0

    print("=== REQUIRED FILES ===")

    for path in REQUIRED_FILES:
        if path.exists():
            print(
                "OK     ",
                path.relative_to(ROOT),
            )
        else:
            print(
                "MISSING",
                path.relative_to(ROOT),
            )
            issues.append(
                f"Missing required file: {path}"
            )

    print()
    print("=== HTML AUDIT ===")

    for path in public_html_files():
        public_count += 1

        text, page = parse_page(path)
        rel = path.relative_to(ROOT)

        robots = page.meta.get("robots", "").lower()
        noindex = "noindex" in robots

        if noindex:
            noindex_count += 1
        else:
            indexable_count += 1

        canonical = (
            page.links[0]
            if page.links
            else ""
        )

        basic_required = {
            "title": page.title,
            "description": page.meta.get(
                "description", ""
            ),
            "canonical": canonical,
        }

        for name, value in basic_required.items():
            if not value:
                issues.append(
                    f"{rel}: missing {name}"
                )

        if canonical:
            canonicals[canonical].append(
                str(rel)
            )

            if not (
                canonical == CANONICAL_ORIGIN
                or canonical.startswith(
                    CANONICAL_ORIGIN + "/"
                )
            ):
                issues.append(
                    f"{rel}: non-www canonical "
                    f"{canonical}"
                )

        if not noindex:
            required = {
                "og:title":
                    page.meta.get("og:title", ""),
                "og:description":
                    page.meta.get(
                        "og:description", ""
                    ),
                "og:url":
                    page.meta.get("og:url", ""),
                "og:image":
                    page.meta.get("og:image", ""),
                "twitter:card":
                    page.meta.get(
                        "twitter:card", ""
                    ),
                "twitter:title":
                    page.meta.get(
                        "twitter:title", ""
                    ),
                "twitter:description":
                    page.meta.get(
                        "twitter:description", ""
                    ),
                "twitter:image":
                    page.meta.get(
                        "twitter:image", ""
                    ),
            }

            for name, value in required.items():
                if not value:
                    issues.append(
                        f"{rel}: missing {name}"
                    )

            if page.jsonld == 0:
                issues.append(
                    f"{rel}: missing JSON-LD"
                )

            if canonical:
                indexable_urls.add(canonical)

        head_match = re.search(
            r"<head\b.*?</head>",
            text,
            re.I | re.S,
        )

        if head_match:
            head = head_match.group(0)

            for bad_host in (
                "new.wanttoknow.info",
                "archive.wanttoknow.info",
                "localhost",
            ):
                if bad_host in head:
                    issues.append(
                        f"{rel}: {bad_host} "
                        f"found in <head>"
                    )

    print(f"Public HTML:       {public_count:,}")
    print(f"Indexable HTML:    {indexable_count:,}")
    print(f"Noindex HTML:      {noindex_count:,}")
    print(
        f"Unique canonicals: {len(canonicals):,}"
    )

    duplicates = {
        url: files
        for url, files in canonicals.items()
        if len(files) > 1
    }

    print(
        f"Duplicate canonical URLs: "
        f"{len(duplicates):,}"
    )

    for url, files in duplicates.items():
        issues.append(
            "Duplicate canonical: "
            + url
            + " <- "
            + ", ".join(files)
        )

    print()
    print("=== SITEMAP AUDIT ===")

    sitemap = SITE / "sitemap.xml"

    try:
        tree = ET.parse(sitemap)

        ns = {
            "sm":
                "http://www.sitemaps.org/"
                "schemas/sitemap/0.9"
        }

        sitemap_urls = {
            el.text.strip()
            for el in tree.findall(
                ".//sm:loc",
                ns,
            )
            if el.text
        }

        print(
            f"Sitemap URLs:      "
            f"{len(sitemap_urls):,}"
        )

        missing = indexable_urls - sitemap_urls
        extra = sitemap_urls - indexable_urls

        print(
            f"Missing from sitemap: "
            f"{len(missing):,}"
        )
        print(
            f"Extra in sitemap:     "
            f"{len(extra):,}"
        )

        for url in sorted(missing):
            issues.append(
                f"Missing from sitemap: {url}"
            )

        for url in sorted(extra):
            issues.append(
                f"Extra in sitemap: {url}"
            )

        for url in sitemap_urls:
            if not (
                url == CANONICAL_ORIGIN
                or url.startswith(
                    CANONICAL_ORIGIN + "/"
                )
            ):
                issues.append(
                    f"Non-www sitemap URL: {url}"
                )

    except Exception as exc:
        issues.append(
            f"Sitemap XML error: {exc}"
        )

    print()
    print("=== RESULT ===")

    if issues:
        print(
            f"FOUND {len(issues)} ISSUE(S)"
        )
        print()

        for issue in issues:
            print(" -", issue)

        raise SystemExit(1)

    print(
        "PASS — no pre-cutover metadata "
        "or sitemap problems found."
    )


if __name__ == "__main__":
    main()
