#!/usr/bin/env python3

from pathlib import Path
from html import escape, unescape
import re

ROOT = Path("/srv/wanttoknow/site")
SITE = ROOT / "src/site"
OUTPUT = SITE / "sitemap.xml"

CANONICAL_ORIGIN = "https://www.wanttoknow.info"

SKIP_PARTS = {
    ".git",
}

canonical_re = re.compile(
    r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
    re.I,
)

noindex_re = re.compile(
    r'<meta[^>]+name=["\']robots["\'][^>]+content=["\'][^"\']*noindex',
    re.I,
)


def public_html_files():
    for path in SITE.rglob("*.html"):
        rel = path.relative_to(SITE)

        if rel.parts and rel.parts[0] == "data":
            continue

        if any(part in SKIP_PARTS for part in rel.parts):
            continue

        name = path.name.lower()

        if ".bak" in name:
            continue

        if ".pre-" in name:
            continue

        yield path


def main():
    urls = set()

    skipped_noindex = []
    skipped_no_canonical = []
    skipped_external = []

    for path in public_html_files():
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

        if noindex_re.search(text):
            skipped_noindex.append(path)
            continue

        match = canonical_re.search(text)

        if not match:
            skipped_no_canonical.append(path)
            continue

        url = unescape(match.group(1).strip())

        if not (
            url == CANONICAL_ORIGIN
            or url.startswith(CANONICAL_ORIGIN + "/")
        ):
            skipped_external.append((path, url))
            continue

        urls.add(url)

    urls = sorted(urls)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for url in urls:
        lines.append("  <url>")
        lines.append(
            f"    <loc>{escape(url, quote=False)}</loc>"
        )
        lines.append("  </url>")

    lines.append("</urlset>")
    lines.append("")

    OUTPUT.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print(f"Wrote: {OUTPUT}")
    print(f"Canonical URLs:       {len(urls):,}")
    print(f"Noindex excluded:     {len(skipped_noindex):,}")
    print(f"No canonical:         {len(skipped_no_canonical):,}")
    print(f"External canonical:   {len(skipped_external):,}")

    if skipped_noindex:
        print("\nNoindex exclusions:")
        for path in skipped_noindex:
            print(
                "  ",
                path.relative_to(ROOT),
            )

    if skipped_no_canonical:
        print("\nWARNING — missing canonical:")
        for path in skipped_no_canonical:
            print(
                "  ",
                path.relative_to(ROOT),
            )

    if skipped_external:
        print("\nWARNING — external canonical:")
        for path, url in skipped_external:
            print(
                "  ",
                path.relative_to(ROOT),
                "->",
                url,
            )


if __name__ == "__main__":
    main()
