#!/usr/bin/env python3

from pathlib import Path
from datetime import datetime
import html
import json
import re
import shutil

ROOT = Path("/srv/wanttoknow/site")
SITE = ROOT / "src/site"

SOCIAL_URL = (
    "https://www.wanttoknow.info/"
    "assets/social/wtk-home-share-1200x630.jpg"
)

FILES = [
    SITE / "about/index.html",
    SITE / "about/team.html",
    SITE / "about/founder/index.html",
    SITE / "about/contributors/index.html",
]


def extract(pattern, text, label):
    match = re.search(pattern, text, re.I | re.S)

    if not match:
        raise RuntimeError(f"Could not find {label}")

    value = re.sub(r"\s+", " ", match.group(1)).strip()
    return html.unescape(value)


def main():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    backup = (
        ROOT.parent
        / "backups"
        / f"about-meta-{stamp}"
    )
    backup.mkdir(parents=True, exist_ok=True)

    print(f"Backup: {backup}")
    print()

    for path in FILES:
        text = path.read_text(encoding="utf-8")

        shutil.copy2(
            path,
            backup / (
                str(path.relative_to(SITE))
                .replace("/", "--")
            ),
        )

        title = extract(
            r"<title>(.*?)</title>",
            text,
            "title",
        )

        description = extract(
            r'<meta\s+name=["\']description["\']\s+'
            r'content=["\'](.*?)["\']',
            text,
            "description",
        )

        canonical = extract(
            r'<link\s+rel=["\']canonical["\']\s+'
            r'href=["\'](.*?)["\']',
            text,
            "canonical",
        )

        # Add Open Graph image if missing.
        if 'property="og:image"' not in text:
            marker = re.search(
                r'<meta[^>]+property=["\']og:description["\'][^>]*>',
                text,
                re.I | re.S,
            )

            if not marker:
                raise RuntimeError(
                    f"{path}: og:description not found"
                )

            block = f"""

  <meta
    property="og:image"
    content="{SOCIAL_URL}"
  >
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta
    property="og:image:alt"
    content="WantToKnow.info — verifiable information and inspiring solutions"
  >"""

            pos = marker.end()
            text = text[:pos] + block + text[pos:]

        # Add Twitter image if missing.
        if 'name="twitter:image"' not in text:
            marker = re.search(
                r'<meta[^>]+name=["\']twitter:description["\'][^>]*>',
                text,
                re.I | re.S,
            )

            if not marker:
                raise RuntimeError(
                    f"{path}: twitter:description not found"
                )

            block = f"""

  <meta
    name="twitter:image"
    content="{SOCIAL_URL}"
  >
  <meta
    name="twitter:image:alt"
    content="WantToKnow.info — verifiable information and inspiring solutions"
  >"""

            pos = marker.end()
            text = text[:pos] + block + text[pos:]

        # Add JSON-LD only where missing.
        if "application/ld+json" not in text:
            schema = {
                "@context": "https://schema.org",
                "@type": "AboutPage",
                "@id": canonical + "#webpage",
                "url": canonical,
                "name": title,
                "description": description,
                "isPartOf": {
                    "@id": "https://www.wanttoknow.info/#website"
                },
                "publisher": {
                    "@id": "https://www.wanttoknow.info/#organization"
                },
                "inLanguage": "en-US",
            }

            block = (
                "\n\n  <script type=\"application/ld+json\">\n"
                + json.dumps(
                    schema,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n  </script>"
            )

            head_end = re.search(
                r"</head>",
                text,
                re.I,
            )

            if not head_end:
                raise RuntimeError(
                    f"{path}: </head> not found"
                )

            pos = head_end.start()
            text = text[:pos] + block + "\n" + text[pos:]

        path.write_text(
            text,
            encoding="utf-8",
        )

        print(
            "UPDATED ",
            path.relative_to(ROOT),
        )

    print()
    print("Done.")


if __name__ == "__main__":
    main()
