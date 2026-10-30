#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import html
import json
import re
import shutil

ROOT = Path("/srv/wanttoknow/site")
SITE = ROOT / "src/site"
TIMELINES = SITE / "timelines"

ORIGIN = "https://www.wanttoknow.info"

SOCIAL_PATH = SITE / "assets/social/wtk-home-share-1200x630.jpg"
SOCIAL_URL = f"{ORIGIN}/assets/social/wtk-home-share-1200x630.jpg"

START = "<!-- WTK TIMELINE META START -->"
END = "<!-- WTK TIMELINE META END -->"

PAGES = {
    "war-on-drugs.html": {
        "title": "War on Drugs Timeline | WantToKnow.info",
        "description": (
            "A sourced timeline tracing the history of the War on Drugs, "
            "drug policy, organized crime, intelligence operations, and "
            "related government actions."
        ),
    },

    "disclosure.html": {
        "title": "UFO Disclosure Timeline | WantToKnow.info",
        "description": (
            "A chronological guide to major UFO and UAP disclosure events, "
            "government programs, whistleblower testimony, investigations, "
            "and legislation."
        ),
    },

    "human-guinea-pigs.html": {
        "title": "Human Guinea Pigs Timeline | WantToKnow.info",
        "description": (
            "A sourced timeline of government programs and experiments that "
            "used people as unwitting or inadequately informed research subjects."
        ),
    },

    "remote-viewing.html": {
        "title": "Remote Viewing Timeline | WantToKnow.info",
        "description": (
            "A sourced timeline of U.S. government remote viewing research, "
            "psychic spying programs, key experiments, and declassified records."
        ),
    },

    "911-facts.html": {
        "title": "9/11 Facts Timeline | WantToKnow.info",
        "description": (
            "A sourced chronological timeline of significant events, evidence, "
            "investigations, and unresolved questions surrounding the attacks "
            "of September 11, 2001."
        ),
    },
}


def strip_existing_block(text):
    pattern = re.compile(
        re.escape(START) + r".*?" + re.escape(END) + r"\s*",
        re.S,
    )
    return pattern.sub("", text)


def replace_title(text, title):
    replacement = f"<title>{html.escape(title)}</title>"

    new_text, count = re.subn(
        r"<title>.*?</title>",
        replacement,
        text,
        count=1,
        flags=re.S | re.I,
    )

    if count != 1:
        raise RuntimeError("Expected exactly one <title>")

    return new_text


def replace_description(text, description):
    replacement = (
        '<meta name="description" '
        f'content="{html.escape(description, quote=True)}">'
    )

    pattern = re.compile(
        r'<meta\s+name=["\']description["\']\s+content=["\'].*?["\']\s*/?>',
        re.S | re.I,
    )

    new_text, count = pattern.subn(
        replacement,
        text,
        count=1,
    )

    if count != 1:
        raise RuntimeError(
            "Expected exactly one meta description"
        )

    return new_text


def build_meta(filename, title, description):
    canonical = f"{ORIGIN}/timelines/{filename}"

    title_attr = html.escape(title, quote=True)
    desc_attr = html.escape(description, quote=True)
    url_attr = html.escape(canonical, quote=True)

    schema = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "@id": canonical + "#webpage",
        "url": canonical,
        "name": title.replace(" | WantToKnow.info", ""),
        "description": description,
        "isPartOf": {
            "@id": f"{ORIGIN}/#website",
        },
        "publisher": {
            "@id": f"{ORIGIN}/#organization",
        },
        "inLanguage": "en-US",
    }

    lines = [
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
    ]

    if SOCIAL_PATH.is_file():
        lines += [
            f'  <meta property="og:image" content="{SOCIAL_URL}">',
            '  <meta property="og:image:type" content="image/jpg">',
            '  <meta property="og:image:width" content="1200">',
            '  <meta property="og:image:height" content="630">',
            (
                '  <meta property="og:image:alt" '
                'content="WantToKnow.info — verifiable information '
                'and inspiring solutions">'
            ),
        ]

    lines += [
        "",
        '  <meta name="twitter:card" content="summary_large_image">',
        f'  <meta name="twitter:title" content="{title_attr}">',
        f'  <meta name="twitter:description" content="{desc_attr}">',
    ]

    if SOCIAL_PATH.is_file():
        lines += [
            f'  <meta name="twitter:image" content="{SOCIAL_URL}">',
            (
                '  <meta name="twitter:image:alt" '
                'content="WantToKnow.info — verifiable information '
                'and inspiring solutions">'
            ),
        ]

    lines += [
        "",
        '  <script type="application/ld+json">',
        json.dumps(schema, indent=2, ensure_ascii=False),
        "  </script>",
        END,
    ]

    return "\n".join(lines)


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = ROOT / "backups" / f"timeline-meta-{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    print(f"Backup: {backup_dir}")
    print()

    if SOCIAL_PATH.is_file():
        print("Social card found; image metadata WILL be added.")
    else:
        print("Social card not found.")
        print("Image metadata will be omitted for now.")
        print("Rerun after creating:")
        print(f"  {SOCIAL_PATH}")

    print()

    for filename, values in PAGES.items():
        path = TIMELINES / filename

        if not path.is_file():
            raise FileNotFoundError(path)

        text = path.read_text(encoding="utf-8")

        shutil.copy2(
            path,
            backup_dir / filename,
        )

        text = strip_existing_block(text)

        text = replace_title(
            text,
            values["title"],
        )

        text = replace_description(
            text,
            values["description"],
        )

        meta = build_meta(
            filename,
            values["title"],
            values["description"],
        )

        title_match = re.search(
            r"</title>",
            text,
            flags=re.I,
        )

        if not title_match:
            raise RuntimeError(
                f"{filename}: </title> not found"
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

        print(f"UPDATED  {path.relative_to(ROOT)}")

    print()
    print("Done.")


if __name__ == "__main__":
    main()