#!/usr/bin/env python3
"""
Generate WantToKnow.info news category index pages.

Reads:
    src/site/data/news-category-map.json
or:
    src/site/assets/data/news-category-map.json

Writes:
    src/site/news/category/<category-slug>/index.html

Each generated page contains:
    - standard dynamic header
    - pretty "<Category> News" title
    - centered 60rem news feed filtered to that category
    - existing sort controls:
        Newest
        Oldest
        Date Posted
        Priority
    - standard dynamic footer
"""

from __future__ import annotations

import html
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = PROJECT_ROOT / "src" / "site"

CATEGORY_MAP_CANDIDATES = [
    SITE_ROOT / "data" / "news-category-map.json",
    SITE_ROOT / "assets" / "data" / "news-category-map.json",
]

ARTICLE_LIMIT = 100


def find_category_map() -> Path:
    for path in CATEGORY_MAP_CANDIDATES:
        if path.exists():
            return path

    searched = "\n".join(
        f"  - {path}"
        for path in CATEGORY_MAP_CANDIDATES
    )

    raise FileNotFoundError(
        "Could not find news-category-map.json.\n"
        f"Searched:\n{searched}"
    )


def load_category_map(path: Path) -> dict:
    with path.open(
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(
            "news-category-map.json must contain "
            "a top-level JSON object."
        )

    return data


def normalize_categories(
    category_map: dict,
) -> list[dict[str, str]]:
    categories = []

    for slug, raw in category_map.items():
        if not isinstance(raw, dict):
            continue

        slug = str(slug).strip()

        if not slug:
            continue

        label = str(
            raw.get("label")
            or slug
        ).strip()

        categories.append(
            {
                "slug": slug,
                "label": label,
            }
        )

    categories.sort(
        key=lambda item: (
            item["label"].casefold(),
            item["slug"].casefold(),
        )
    )

    return categories


def make_page(
    category_slug: str,
    category_label: str,
) -> str:
    page_title = f"{category_label} News"

    description = (
        f"Browse WantToKnow.info news summaries "
        f"related to {category_label}."
    )

    canonical = (
        "https://www.wanttoknow.info"
        f"/news/category/{category_slug}/"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">

  <meta
    name="viewport"
    content="width=device-width, initial-scale=1"
  >

  <meta
    name="theme-color"
    content="#7658f6"
  >

  <meta
    name="color-scheme"
    content="light"
  >


  <title>{html.escape(page_title)} | WantToKnow.info</title>

  <meta
    name="description"
    content="{html.escape(description, quote=True)}"
  >

  <meta
    name="robots"
    content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
  >

  <link
    rel="canonical"
    href="{html.escape(canonical, quote=True)}"
  >


  <meta
    property="og:type"
    content="website"
  >

  <meta
    property="og:site_name"
    content="WantToKnow.info"
  >

  <meta
    property="og:locale"
    content="en_US"
  >

  <meta
    property="og:url"
    content="{html.escape(canonical, quote=True)}"
  >

  <meta
    property="og:title"
    content="{html.escape(page_title, quote=True)} | WantToKnow.info"
  >

  <meta
    property="og:description"
    content="{html.escape(description, quote=True)}"
  >

  <meta
    property="og:image"
    content="https://www.wanttoknow.info/assets/social/wtk-home-share-1200x630.jpg"
  >


  <meta
    name="twitter:card"
    content="summary_large_image"
  >

  <meta
    name="twitter:title"
    content="{html.escape(page_title, quote=True)} | WantToKnow.info"
  >

  <meta
    name="twitter:description"
    content="{html.escape(description, quote=True)}"
  >

  <meta
    name="twitter:image"
    content="https://www.wanttoknow.info/assets/social/wtk-home-share-1200x630.jpg"
  >


  <meta
    name="application-name"
    content="WantToKnow.info"
  >

  <meta
    name="apple-mobile-web-app-title"
    content="WantToKnow.info"
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

  <link
    rel="manifest"
    href="/site.webmanifest"
  >


  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    "@id": "{canonical}#webpage",
    "url": "{canonical}",
    "name": {json.dumps(page_title)},
    "description": {json.dumps(description)},
    "isPartOf": {{
      "@id": "https://www.wanttoknow.info/#website"
    }},
    "inLanguage": "en-US"
  }}
  </script>


  <link
    rel="stylesheet"
    href="/assets/css/global.css"
  >


  <style>
    /* ========================================================================
       News category page
       ======================================================================== */

    .category-index {{
      padding-block:
        clamp(1.75rem, 3vw, 2.75rem)
        0;
    }}


    .category-index__inner {{
      width: min(100%, 60rem);
      margin-inline: auto;
    }}


    .category-index__title {{
      margin: 0;

      max-width: 18ch;

      font-size:
        clamp(2.75rem, 7vw, 6rem);

      line-height: 0.96;

      letter-spacing: -0.055em;

      text-wrap: balance;
    }}


    .category-index__articles {{
      padding-block:
        clamp(1.75rem, 3vw, 2.75rem);
    }}


    .category-index__articles-inner {{
      width: min(100%, 60rem);
      margin-inline: auto;
    }}


    .category-index__feed {{
      display: block;
      width: 100%;
    }}
  </style>

</head>


<body>

  <a
    class="skip-link"
    href="#main-content"
  >
    Skip to main content
  </a>


  <!-- Standard dynamic header -->
  <div
    id="global-header"
    data-global-header
  ></div>


  <main id="main-content">

    <section
      class="category-index"
      aria-labelledby="category-index-title"
    >
      <div class="container">

        <div class="category-index__inner">

          <p class="eyebrow">
            News category
          </p>

          <h1
            class="category-index__title"
            id="category-index-title"
          >
            {html.escape(page_title)}
          </h1>

        </div>

      </div>
    </section>


    <section
      class="category-index__articles"
      aria-label="{html.escape(category_label, quote=True)} news articles"
    >
      <div class="container">

        <div class="category-index__articles-inner">

          <wtk-news-feed
            class="category-index__feed"
            tags="{html.escape(category_slug, quote=True)}"
            tag-mode="any"
            limit="{ARTICLE_LIMIT}"
            sort="newest"
            aria-label="{html.escape(category_label, quote=True)} news articles"
          >
          </wtk-news-feed>

        </div>

      </div>
    </section>

  </main>


  <!-- Standard dynamic footer -->
  <div
    id="global-footer"
    data-global-footer
  ></div>


  <script
    src="/assets/js/global.js"
    defer
  ></script>

  <script
    type="module"
    src="/assets/js/components/news-feed.js"
  ></script>

</body>
</html>
"""


def main() -> None:
    category_map_path = find_category_map()

    print(
        f"Using category map: "
        f"{category_map_path}"
    )

    category_map = load_category_map(
        category_map_path
    )

    categories = normalize_categories(
        category_map
    )

    generated = 0

    for category in categories:
        slug = category["slug"]
        label = category["label"]

        output_dir = (
            SITE_ROOT
            / "news"
            / "category"
            / slug
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            output_dir
            / "index.html"
        )

        page = make_page(
            slug,
            label,
        )

        output_path.write_text(
            page,
            encoding="utf-8",
            newline="\n",
        )

        generated += 1

        print(
            f"{label:<36} "
            f"→ /news/category/{slug}/"
        )

    print()
    print(
        f"Generated {generated} category pages."
    )


if __name__ == "__main__":
    main()
