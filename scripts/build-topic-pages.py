#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = PROJECT_ROOT / 'src' / 'site'

CATEGORY_MAP_CANDIDATES = [
    SITE_ROOT / 'data' / 'news-category-map.json',
    SITE_ROOT / 'assets' / 'data' / 'news-category-map.json',
]

ARTICLE_LIMIT = 100

TOPICS = {
    'inspiring': 'Inspiring',
    'health': 'Health + Medicine',
    'money': 'Money + Power',
    'media': 'Media',
    'tech': 'Privacy + Technology',
    'government': 'Government + Intelligence',
    'war': 'War + Security',
    'mind-control': 'Mind Control',
    'abuse-and-trafficking': 'Abuse + Trafficking',
    'science-and-environment': 'Environment + Science',
    'consciousness': 'Reality + Consciousness',
    'ufo': 'UFO/UAP Disclosure',
    'deep-history': 'Deep History',
}


def find_category_map() -> Path:
    for path in CATEGORY_MAP_CANDIDATES:
        if path.exists():
            return path
    searched = '\n'.join(f'  - {path}' for path in CATEGORY_MAP_CANDIDATES)
    raise FileNotFoundError(
        'Could not find news-category-map.json.\n'
        f'Searched:\n{searched}'
    )


def load_category_map(path: Path) -> dict:
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError('news-category-map.json must contain a top-level JSON object.')
    return data


def categories_for_topic(category_map: dict, topic_slug: str) -> list[dict[str, str]]:
    categories = []
    for category_slug, raw in category_map.items():
        if not isinstance(raw, dict):
            continue
        primary_topic = str(raw.get('topic') or '').strip()
        secondary_topics = raw.get('secondary_topics') or []
        if not isinstance(secondary_topics, list):
            secondary_topics = []
        if primary_topic != topic_slug and topic_slug not in secondary_topics:
            continue
        categories.append({
            'slug': category_slug,
            'label': str(raw.get('label') or category_slug).strip(),
        })
    categories.sort(key=lambda item: (item['label'].casefold(), item['slug'].casefold()))
    return categories


def category_pills(categories: list[dict[str, str]]) -> str:
    return '\n'.join(
        f'''          <a\n            class="topic-index__pill"\n            href="/news/category/{html.escape(item['slug'], quote=True)}/"\n          >\n            {html.escape(item['label'])}\n          </a>'''
        for item in categories
    )


def make_page(topic_slug: str, topic_name: str, categories: list[dict[str, str]]) -> str:
    title = f'{topic_name} Index'
    description = f'Explore WantToKnow.info news summaries and categories related to {topic_name}.'
    canonical = f'https://www.wanttoknow.info/topics/{topic_slug}/'
    tag_list = ','.join(item['slug'] for item in categories)
    pills = category_pills(categories)

    structured_title = json.dumps(title, ensure_ascii=False)[1:-1]
    structured_description = json.dumps(description, ensure_ascii=False)[1:-1]

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#7658f6">
  <meta name="color-scheme" content="light">

  <title>{html.escape(title)} | WantToKnow.info</title>

  <meta
    name="description"
    content="{html.escape(description, quote=True)}"
  >
  <meta
    name="robots"
    content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
  >
  <link rel="canonical" href="{html.escape(canonical, quote=True)}">

  <meta property="og:type" content="website">
  <meta property="og:site_name" content="WantToKnow.info">
  <meta property="og:locale" content="en_US">
  <meta property="og:url" content="{html.escape(canonical, quote=True)}">
  <meta property="og:title" content="{html.escape(title, quote=True)} | WantToKnow.info">
  <meta property="og:description" content="{html.escape(description, quote=True)}">
  <meta property="og:image" content="https://www.wanttoknow.info/assets/social/wtk-home-share-1200x630.jpg">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(title, quote=True)} | WantToKnow.info">
  <meta name="twitter:description" content="{html.escape(description, quote=True)}">
  <meta name="twitter:image" content="https://www.wanttoknow.info/assets/social/wtk-home-share-1200x630.jpg">

  <meta name="application-name" content="WantToKnow.info">
  <meta name="apple-mobile-web-app-title" content="WantToKnow.info">

  <link rel="icon" type="image/x-icon" href="/assets/images/favicon.ico">
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/images/favicon-32x32.png">
  <link rel="icon" type="image/png" sizes="16x16" href="/assets/images/favicon-16x16.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/assets/images/apple-touch-icon.png">
  <link rel="manifest" href="/site.webmanifest">

  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "CollectionPage",
    "@id": "{canonical}#webpage",
    "url": "{canonical}",
    "name": "{structured_title}",
    "description": "{structured_description}",
    "isPartOf": {{
      "@id": "https://www.wanttoknow.info/#website"
    }},
    "inLanguage": "en-US"
  }}
  </script>

  <link rel="stylesheet" href="/assets/css/global.css">

  <style>
    .topic-index {{
      padding-block: clamp(1.75rem, 3vw, 2.75rem) 0;
    }}

    .topic-index__title {{
      margin: 0;
      max-width: 18ch;
      font-size: clamp(2.75rem, 7vw, 6rem);
      line-height: 0.96;
      letter-spacing: -0.055em;
      text-wrap: balance;
    }}

    .topic-index__categories {{
      display: flex;
      flex-wrap: wrap;
      gap: var(--layout-grid-gap, clamp(0.9rem, 2vw, 1.5rem));
      margin-top: clamp(1.5rem, 3vw, 2.25rem);
    }}

    .topic-index__pill {{
      display: inline-flex;
      align-items: center;
      min-height: 2.5rem;
      padding: 0.55rem 0.85rem;
      border: 1px solid var(--color-border, #d7d1df);
      color: inherit;
      text-decoration: none;
      transition: border-color 150ms ease, background-color 150ms ease;
    }}

    .topic-index__pill:hover {{
      border-color: var(--color-accent, #7658f6);
      background: var(--color-accent-soft, #f3f0ff);
    }}

    .topic-index__pill:focus-visible {{
      outline: 2px solid var(--color-accent, #7658f6);
      outline-offset: 2px;
    }}

    .topic-index__articles {{
      padding-block: clamp(1.75rem, 3vw, 2.75rem);
    }}

    .topic-index__articles-inner {{
      width: min(100%, 60rem);
      margin-inline: auto;
    }}

    .topic-index__articles-heading {{
      margin-bottom: var(--layout-grid-gap, clamp(0.9rem, 2vw, 1.5rem));
    }}

    .topic-index__articles-heading h2 {{
      margin-bottom: 0;
    }}

    .topic-index__feed {{
      display: block;
      width: 100%;
    }}

    @media (prefers-reduced-motion: reduce) {{
      .topic-index__pill {{
        transition: none;
      }}
    }}
  </style>
</head>

<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>

  <div id="global-header" data-global-header></div>

  <main id="main-content">
    <section class="topic-index" aria-labelledby="topic-index-title">
      <div class="container">
        <p class="eyebrow">Explore by topic</p>

        <h1 class="topic-index__title" id="topic-index-title">
          {html.escape(title)}
        </h1>

        <nav
          class="topic-index__categories"
          aria-label="{html.escape(topic_name, quote=True)} categories"
        >
{pills}
        </nav>
      </div>
    </section>

    <section class="topic-index__articles" aria-labelledby="topic-news-title">
      <div class="container">
        <div class="topic-index__articles-inner">
          <header class="topic-index__articles-heading">
            <p class="eyebrow">News archive</p>

            <h2 class="section-title" id="topic-news-title">
              {html.escape(topic_name)} News
            </h2>
          </header>

          <wtk-news-feed
            class="topic-index__feed"
            tags="{html.escape(tag_list, quote=True)}"
            tag-mode="any"
            limit="{ARTICLE_LIMIT}"
            sort="newest"
            aria-label="{html.escape(topic_name, quote=True)} news articles"
          ></wtk-news-feed>
        </div>
      </div>
    </section>
  </main>

  <div id="global-footer" data-global-footer></div>

  <script src="/assets/js/global.js" defer></script>
  <script type="module" src="/assets/js/components/news-feed.js"></script>
</body>
</html>
'''


def main() -> None:
    category_map_path = find_category_map()
    print(f'Using category map: {category_map_path}')
    category_map = load_category_map(category_map_path)

    generated = 0
    for topic_slug, topic_name in TOPICS.items():
        categories = categories_for_topic(category_map, topic_slug)
        if not categories:
            print(f'WARNING: no categories found for {topic_slug}; skipping.')
            continue

        output_dir = SITE_ROOT / 'topics' / topic_slug
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / 'index.html'
        output_path.write_text(
            make_page(topic_slug, topic_name, categories),
            encoding='utf-8',
            newline='\n',
        )

        generated += 1
        print(
            f'{topic_name:<30} {len(categories):>3} categories '
            f'→ {output_path}'
        )

    print()
    print(f'Generated {generated} topic pages.')


if __name__ == '__main__':
    main()
