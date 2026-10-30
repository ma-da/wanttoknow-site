#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import html
import json
import re
import shutil

ROOT = Path("/srv/wanttoknow/site")
SITE = ROOT / "src/site"

ORIGIN = "https://www.wanttoknow.info"
SOCIAL_URL = f"{ORIGIN}/assets/social/wtk-home-share-1200x630.jpg"

START = "<!-- WTK RESEARCH PORTAL META START -->"
END = "<!-- WTK RESEARCH PORTAL META END -->"

PAGES = {
    SITE / "search/mkultra/index.html": {
        "canonical": f"{ORIGIN}/search/mkultra/",
    },
    SITE / "search/cointelpro/index.html": {
        "canonical": f"{ORIGIN}/search/cointelpro/",
    },
}


def extract_title(text):
    match = re.search(
        r"<title>(.*?)</title>",
        text,
        flags=re.I | re.S,
    )
    if not match:
        raise RuntimeError("Missing <title>")

    return html.unescape(
        re.sub(r"\s+", " ", match.group(1)).strip()
    )


def extract_description(text):
    match = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']\s*/?>',
        text,
        flags=re.I | re.S,
    )
    if not match:
        raise RuntimeError("Missing meta description")

    return html.unescape(
        re.sub(r"\s+", " ", match.group(1)).strip()
    )


def strip_existing_block(text):
    pattern = re.compile(
        re.escape(START) + r".*?" + re.escape(END) + r"\s*",
        flags=re.S,
    )
    return pattern.sub("", text)


def build_meta(title, description, canonical):
    title_attr = html.escape(title, quote=True)
    desc_attr = html.escape(description, quote=True)
    url_attr = html.escape(canonical, quote=True)

    schema = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "@id": canonical + "#webpage",
        "url": canonical,
        "name": title.replace(" | WantToKnow.info", ""),
        "description": description,
        "isPartOf": {
            "@id": f"{ORIGIN}/#website"
        },
        "publisher": {
            "@id": f"{ORIGIN}/#organization"
        },
        "inLanguage": "en-US",
    }

    return "\n".join([
        START,

        '  <meta name="robots" '
        'content="index, follow, max-image-preview:large, '
        'max-snippet:-1, max-video-preview:-1">',

        "",
        f'  <link rel="canonical" href="{url_attr}">',

        "",
        '  <meta property="og:type" content="website">',
        '  <meta property="og:site_name" content="WantToKnow.info">',
        '  <meta property="og:locale" content="en_US">',
        f'  <meta property="og:url" content="{url_attr}">',
        f'  <meta property="og:title" content="{title_attr}">',
        f'  <meta property="og:description" content="{desc_attr}">',
        f'  <meta property="og:image" content="{SOCIAL_URL}">',
        '  <meta property="og:image:type" content="image/jpeg">',
        '  <meta property="og:image:width" content="1200">',
        '  <meta property="og:image:height" content="630">',
        '  <meta property="og:image:alt" '
        'content="WantToKnow.info — verifiable information and inspiring solutions">',

        "",
        '  <meta name="twitter:card" content="summary_large_image">',
        f'  <meta name="twitter:title" content="{title_attr}">',
        f'  <meta name="twitter:description" content="{desc_attr}">',
        f'  <meta name="twitter:image" content="{SOCIAL_URL}">',
        '  <meta name="twitter:image:alt" '
        'content="WantToKnow.info — verifiable information and inspiring solutions">',

        "",
        '  <script type="application/ld+json">',
        json.dumps(schema, indent=2, ensure_ascii=False),
        "  </script>",

        END,
    ])


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = (
        ROOT.parent
        / "backups"
        / f"research-portal-meta-{stamp}"
    )
    backup_dir.mkdir(parents=True, exist_ok=True)

    print(f"Backup: {backup_dir}")
    print()

    for path, settings in PAGES.items():
        if not path.is_file():
            raise FileNotFoundError(path)

        text = path.read_text(encoding="utf-8")

        title = extract_title(text)
        description = extract_description(text)

        shutil.copy2(
            path,
            backup_dir / path.name.replace(
                "index.html",
                path.parent.name + "-index.html",
            ),
        )

        text = strip_existing_block(text)

        meta = build_meta(
            title,
            description,
            settings["canonical"],
        )

        title_match = re.search(
            r"</title>",
            text,
            flags=re.I,
        )

        if not title_match:
            raise RuntimeError(
                f"{path}: </title> not found"
            )

        insert_at = title_match.end()

        text = (
            text[:insert_at]
            + "\n\n  "
            + meta
            + text[insert_at:]
        )

        path.write_text(
            text,
            encoding="utf-8",
        )

        print(
            f"UPDATED  {path.relative_to(ROOT)}"
        )
        print(f"  Title:     {title}")
        print(
            f"  Canonical: {settings['canonical']}"
        )
        print()

    print("Done.")


if __name__ == "__main__":
    main()
