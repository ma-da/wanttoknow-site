#!/usr/bin/env python3
"""
Generate static WantToKnow.info news article pages.

Examples:
  python scripts/build-news-articles.py --id 14559
  python scripts/build-news-articles.py --slug some-article-slug
  python scripts/build-news-articles.py --all

Requires:
  pip install markdown
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "src" / "site"
DATA = SITE / "data"
NEWS = SITE / "news"

MASTER = DATA / "wtk_articles_master.jsonl"
INDEX = DATA / "article-index.jsonl"
CATEGORY_MAP = DATA / "news-category-map.json"

BODY_WIDTH = "40.625rem"  # 650px at 16px/rem
RELATED_LIMIT = 12

PROCEDURE_HEADING = (
    "Each news summary is created according to strict standards. "
    "Here's how we do it."
)

PROCEDURE_TEXT = (
    "Each summary is created using a consistent editorial procedure. "
    "The target length is approximately 16 lines of 11-point Arial text in a "
    "650-pixel-wide column. Up to 25% of a summary may be set in bold to "
    "emphasize the most important ideas. Summaries are composed of verbatim "
    "excerpts presented in the same sequence as they appear in the original "
    "news source, with very minor editorial additions. Where material has been "
    "omitted between excerpts, the omission is indicated with ellipses (...). "
    "Any words added by an editor for clarity or context appear in [brackets]. "
    "Our original news editor was Fred Burks. Tod Fletcher edited most summaries "
    "from 2007 through 2014, and Mark Bailey has served as news editor since 2014."
)


def args():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--id")
    g.add_argument("--slug")
    g.add_argument("--all", action="store_true")
    return p.parse_args()


def load_jsonl(path: Path):
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Bad JSON in {path.name}, line {n}") from exc
    return rows


def load_labels():
    with CATEGORY_MAP.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return {
        str(slug): str(value.get("label") or slug)
        for slug, value in raw.items()
        if isinstance(value, dict)
    }


def md(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return markdown.markdown(
        value,
        extensions=["extra", "sane_lists"],
        output_format="html5",
    )


def plain(value):
    text = str(value or "")
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`>#]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def meta_description(article):
    text = plain(
        article.get("description_markdown")
        or article.get("summary_markdown")
        or article.get("title")
        or ""
    )
    return text if len(text) <= 158 else text[:155].rstrip() + "..."


def publication_date(value):
    value = str(value or "").strip()
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%B %d, %Y")
    except ValueError:
        return value


def category_html(tags, labels):
    parts = []
    for tag in tags or []:
        slug = str(tag).strip()
        if not slug:
            continue
        label = labels.get(slug, slug.replace("-", " ").replace("_", " ").title())
        parts.append(
            f'<a class="article-category-pill" href="/news/category/{html.escape(slug, quote=True)}/">'
            f'{html.escape(label)}</a>'
        )
    return "\n          ".join(parts)


def image_html(article):
    """
    Build the full-size article image from the Article ID.

    Local file:
        src/site/assets/images/article-images/{ArticleId}i.jpg

    Browser URL:
        /assets/images/article-images/{ArticleId}i.jpg

    If the full-size image does not exist, no hero image is rendered.
    """

    article_id = str(
        article.get("article_id") or ""
    ).strip()

    if not article_id:
        return "", ""

    filename = f"{article_id}i.jpg"

    local_path = (
        SITE
        / "assets"
        / "images"
        / "article-images"
        / filename
    )

    # No full-size image for this article.
    if not local_path.is_file():
        return "", ""

    public_path = (
        f"/assets/images/article-images/"
        f"{filename}"
    )

    caption_markdown = str(
        article.get("image_caption_markdown")
        or ""
    ).strip()

    caption_text = str(
        article.get("image_caption_text")
        or ""
    ).strip()

    if caption_markdown:
        # Escape raw HTML first, then render Markdown formatting.
        caption_body = markdown.markdown(
            html.escape(caption_markdown),
            extensions=[],
            output_format="html5",
        ).strip()
    elif caption_text:
        caption_body = html.escape(caption_text)
    else:
        caption_body = ""

    caption_html = (
        f\'\'\'<figcaption class="article-hero__caption">
          {caption_body}
        </figcaption>\'\'\'
        if caption_body
        else ""
    )

    block = f'''<figure class="article-hero">
      <img
        src="{html.escape(public_path, quote=True)}"
        alt=""
        fetchpriority="high"
        decoding="async"
      >
      {caption_html}
    </figure>'''

    return block, public_path


def related_ids(article, index_by_id):
    aid = str(article.get("article_id"))
    row = index_by_id.get(aid, {})
    values = row.get("related") or article.get("related_articles") or []
    return [str(v).strip() for v in values if str(v).strip()][:RELATED_LIMIT]


def json_ld(article, canonical, description, image_path):
    data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "@id": canonical + "#article",
        "url": canonical,
        "headline": article.get("title") or "",
        "description": description,
        "datePublished": article.get("publication_date") or "",
        "dateCreated": article.get("posted_date") or "",
        "publisher": {
            "@type": "Organization",
            "@id": "https://www.wanttoknow.info/#organization",
            "name": "WantToKnow.info",
            "url": "https://www.wanttoknow.info/",
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "inLanguage": "en-US",
    }

    source = str(article.get("source_url") or "").strip()
    if source:
        data["isBasedOn"] = source

    if image_path:
        data["image"] = [
            image_path if image_path.startswith("http")
            else "https://www.wanttoknow.info" + image_path
        ]

    return json.dumps(data, ensure_ascii=False, indent=2)


def page(article, index_by_id, labels):
    aid = str(article.get("article_id") or "").strip()
    slug = str(article.get("slug") or "").strip()
    title = str(article.get("title") or "Untitled article").strip()

    if not aid or not slug:
        raise ValueError(f"Article missing id or slug: {article!r}")

    canonical = f"https://www.wanttoknow.info/news/{slug}"
    desc = meta_description(article)

    pub_name = str(
        article.get("publication_name")
        or article.get("publication_group")
        or "Unknown publisher"
    ).strip()

    pub_raw = str(article.get("publication_date") or "").strip()
    pub_display = publication_date(pub_raw)
    posted = str(article.get("posted_date") or "").strip()
    priority = str(article.get("priority") if article.get("priority") is not None else "")
    source = str(article.get("source_url") or "").strip()

    summary = md(article.get("summary_markdown"))
    note = md(article.get("note_markdown"))
    tags = category_html(article.get("tags"), labels)
    hero, hero_path = image_html(article)

    rel_ids = related_ids(article, index_by_id)
    rel_attr = ",".join(rel_ids)

    publisher = (
        f'<a class="article-meta__source" href="{html.escape(source, quote=True)}" '
        f'target="_blank" rel="noopener noreferrer">{html.escape(pub_name)}</a>'
        if source else html.escape(pub_name)
    )

    note_block = f'''<aside class="article-note" aria-labelledby="article-note-title">
            <p class="eyebrow" id="article-note-title">Note</p>
            <div class="article-note__body">{note}</div>
          </aside>''' if note else ""

    related_block = f'''<aside class="article-related" aria-labelledby="related-articles-title">
          <p class="eyebrow">Explore</p>
          <h2 id="related-articles-title">Related Articles</h2>
          <wtk-news-feed
            class="article-related__feed"
            ids="{html.escape(rel_attr, quote=True)}"
            limit="{len(rel_ids)}"
            hide-sort
            hide-count
            aria-label="Related articles">
          </wtk-news-feed>
        </aside>''' if rel_ids else ""

    layout_class = "article-layout" if rel_ids else "article-layout article-layout--single"

    social = hero_path or "/assets/social/wtk-home-share-1200x630.jpg"
    social_abs = social if social.startswith("http") else "https://www.wanttoknow.info" + social

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#7658f6">
  <meta name="color-scheme" content="light">

  <title>{html.escape(title)} | WantToKnow.info</title>
  <meta name="description" content="{html.escape(desc, quote=True)}">
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1">
  <link rel="canonical" href="{html.escape(canonical, quote=True)}">

  <meta property="og:type" content="article">
  <meta property="og:site_name" content="WantToKnow.info">
  <meta property="og:url" content="{html.escape(canonical, quote=True)}">
  <meta property="og:title" content="{html.escape(title, quote=True)}">
  <meta property="og:description" content="{html.escape(desc, quote=True)}">
  <meta property="og:image" content="{html.escape(social_abs, quote=True)}">

  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html.escape(title, quote=True)}">
  <meta name="twitter:description" content="{html.escape(desc, quote=True)}">
  <meta name="twitter:image" content="{html.escape(social_abs, quote=True)}">

  <script type="application/ld+json">
{json_ld(article, canonical, desc, hero_path)}
  </script>

  <link rel="icon" type="image/x-icon" href="/assets/images/favicon.ico">
  <link rel="stylesheet" href="/assets/css/global.css">

  <style>
    .article-page {{ padding-bottom: clamp(2.5rem, 6vw, 5rem); }}

    .article-hero {{ width: 100%; margin: 0; }}
    .article-hero img {{ display: block; width: 100%; max-height: 46rem; object-fit: cover; }}
    .article-hero__caption {{
      width: min(
        calc(100% - 2rem),
        40.625rem
      );

      margin-inline: auto;

      padding:
        0.45rem
        0
        0;

      color: var(--color-text-muted);

      font-size: var(--font-size-sm);
      line-height: 1.45;
    }}
    .article-hero__caption > :first-child {{ margin-top: 0; }}
    .article-hero__caption > :last-child {{ margin-bottom: 0; }}

    .article-heading {{
      padding-block:
        1rem
        clamp(1.5rem, 3vw, 2.5rem);
    }}
    .article-heading__inner {{ width: min(calc(100% - 2rem), 72rem); margin-inline: auto; }}
    .article-title {{ max-width: 18ch; margin: 0; font-size: clamp(2.8rem, 7vw, 6.5rem); line-height: .96; letter-spacing: -.055em; text-wrap: balance; }}

    .article-categories {{ display: flex; flex-wrap: wrap; gap: .45rem; margin-top: clamp(1.25rem, 2vw, 1.75rem); }}
    .article-category-pill {{ display: inline-flex; align-items: center; min-height: 2rem; padding: .32rem .65rem; border: var(--border-width) solid var(--border-color); color: var(--color-text); background: var(--color-surface); font-size: .78rem; font-weight: 600; line-height: 1.2; text-decoration: none; }}
    .article-category-pill:hover, .article-category-pill:focus-visible {{ border-color: var(--color-accent); background: var(--color-surface-muted); }}

    .article-meta {{ display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 1rem; margin-top: clamp(1.5rem, 3vw, 2.5rem); padding-block: 1rem; border-block: var(--border-width) solid var(--border-color); }}
    .article-meta__label {{ display: block; margin-bottom: .25rem; color: var(--color-text-muted); font-size: .7rem; font-weight: 700; letter-spacing: .08em; line-height: 1.2; text-transform: uppercase; }}
    .article-meta__value {{ display: block; font-size: .92rem; line-height: 1.4; }}
    .article-meta__source {{ color: inherit; text-underline-offset: .16em; }}

    .article-content-shell {{ width: min(calc(100% - 2rem), 64rem); margin-inline: auto; }}
    .article-layout {{ display: grid; grid-template-columns: minmax(0, {BODY_WIDTH}) minmax(14rem, 18rem); justify-content: center; align-items: start; gap: clamp(2rem, 4vw, 4rem); }}
    .article-layout--single {{ grid-template-columns: minmax(0, {BODY_WIDTH}); }}
    .article-main {{
      min-width: 0;
    }}

    .article-body {{
      width: 100%;
      max-width: {BODY_WIDTH};

      /*
       * Typography inherits from global.css.
       * Only article-specific reading rhythm is set here.
       */
      line-height: 1.65;
    }}

    .article-body > :first-child {{
      margin-top: 0;
    }}

    .article-body > :last-child {{
      margin-bottom: 0;
    }}

    .article-body p {{
      margin:
        0
        0
        1.05em;
    }}

    .article-body a {{
      overflow-wrap: anywhere;
    }}


    /* ------------------------------------------------------------------------
       Editorial note
       ------------------------------------------------------------------------ */

    .article-note {{
      margin-top:
        clamp(2rem, 4vw, 3rem);

      padding:
        clamp(1rem, 2vw, 1.4rem);

      border-left:
        0.22rem
        solid
        var(--color-accent);

      background:
        var(--color-surface-muted);
    }}

    .article-note .eyebrow {{
      margin-bottom: 0.6rem;
    }}

    .article-note__body {{
      font-family: inherit;
      font-size: inherit;
      line-height: 1.65;
    }}

    .article-note__body > :first-child {{
      margin-top: 0;
    }}

    .article-note__body > :last-child {{
      margin-bottom: 0;
    }}

    /* ------------------------------------------------------------------------
       Related articles
       ------------------------------------------------------------------------ */

    .article-related {{
      min-width: 0;

      padding-left:
        clamp(1rem, 2vw, 1.5rem);

      border-left:
        var(--border-width)
        solid
        var(--border-color);
    }}


    .article-related h2 {{
      margin:
        0
        0
        1rem;

      font-size:
        clamp(1.45rem, 2vw, 1.9rem);

      line-height: 1.05;
    }}


    /*
     * Compact related article:
     *
     * thumbnail 25% | publisher + date
     *               | title
     * ---------------------------------
     * categories span full width
     */

    .article-related__feed .news-feed-item {{
      display: grid;

      grid-template-columns:
        minmax(0, 1fr)
        minmax(0, 3fr);

      grid-template-rows:
        auto
        auto
        auto;

      align-items: start;

      column-gap: 0.65rem;
      row-gap: 0.15rem;
    }}


    .article-related__feed .news-feed-thumb {{
      grid-column: 1;
      grid-row:
        1 / 3;

      width: 100%;
      min-width: 0;
    }}


    .article-related__feed .news-feed-thumb img,
    .article-related__feed .news-feed-thumb-fallback {{
      display: block;

      width: 100%;
      height: auto;
    }}


    /*
     * Flatten the content wrapper so its children
     * can occupy explicit grid positions.
     */

    .article-related__feed .news-feed-content {{
      display: contents;
    }}


    /*
     * Publisher + date sit at the top-right.
     */

    .article-related__feed .news-feed-meta {{
      grid-column: 2;
      grid-row: 1;

      align-self: start;

      margin: 0;

      font-size: 0.6rem;
      line-height: 1.2;
    }}


    /*
     * Title follows immediately beneath metadata.
     */

    .article-related__feed .news-feed-title {{
      grid-column: 2;
      grid-row: 2;

      align-self: start;

      margin:
        0.15rem
        0
        0;

      font-size: 0.92rem;
      line-height: 1.18;
    }}


    /*
     * Categories occupy a compact third row
     * spanning thumbnail + text.
     */

    .article-related__feed .news-feed-tags {{
      grid-column:
        1 / -1;

      grid-row: 3;

      width: 100%;

      margin:
        0.35rem
        0
        0;

      font-size: 0.6rem;
    }}
    
    .article-related__feed .news-feed-tags {{
      grid-column:
        1 / -1;

      grid-row: 3;

      width: 100%;

      margin:
        0.35rem
        0
        0;

      font-size: 0.6rem;
    }}


    .article-related__feed .news-feed-tags a {{
      min-height: 1.4rem;

      padding:
        0.18rem
        0.42rem;

      line-height: 1.1;
    }}    

    .article-latest {{
      width: 100%;

      margin-top:
        clamp(2.5rem, 5vw, 4rem);

      padding-top:
        clamp(1.5rem, 3vw, 2.25rem);

      border-top:
        var(--border-width)
        solid
        var(--border-color);
    }}
    .article-latest__heading {{ margin-bottom: 1.25rem; }}
    .article-latest__heading h2 {{ margin: 0; font-size: clamp(1.8rem, 4vw, 3rem); line-height: 1; }}
    .article-latest__link {{
      color: inherit;
      text-decoration: none;
    }}

    .article-latest__link:hover,
    .article-latest__link:focus-visible {{
      color: var(--color-accent);
      text-decoration: underline;
      text-underline-offset: 0.14em;
    }}    

    .article-procedure {{
      width: 100%;

      margin-top:
        clamp(2.5rem, 5vw, 4rem);

      padding:
        clamp(1.25rem, 3vw, 2rem);

      border: 0;

      background:
        var(--color-brand-tan-light);
    }}
    .article-procedure h2 {{ max-width: 24ch; margin: 0 0 1rem; font-size: clamp(1.65rem, 3vw, 2.5rem); line-height: 1.08; text-wrap: balance; }}
    .article-procedure p {{ max-width: 70ch; margin: 0; color: var(--color-text-muted); line-height: 1.68; }}

    @media (max-width: 64rem) {{
      .article-meta {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    }}

    @media (max-width: 56rem) {{
      .article-layout {{ grid-template-columns: 1fr; }}
      .article-related {{ position: static; padding: 1.5rem 0 0; border-left: 0; border-top: var(--border-width) solid var(--border-color); }}
    }}

    @media (max-width: 36rem) {{
      .article-heading__inner, .article-content-shell {{ width: min(calc(100% - 1.25rem), 100%); }}
      .article-meta {{ grid-template-columns: 1fr; }}
      .article-title {{ font-size: clamp(2.45rem, 13vw, 4.4rem); }}
    }}
  </style>
</head>

<body>
  <a class="skip-link" href="#main-content">Skip to main content</a>

  <div id="global-header" data-global-header></div>

  <main class="article-page" id="main-content">

    {hero}

    <header class="article-heading">
      <div class="article-heading__inner">
        <p class="eyebrow">Curated News</p>
        <h1 class="article-title">{html.escape(title)}</h1>

        <nav class="article-categories" aria-label="Article categories">
          {tags}
        </nav>

        <div class="article-meta">
          <div class="article-meta__item">
            <span class="article-meta__label">Publisher</span>
            <span class="article-meta__value">{publisher}</span>
          </div>

          <div class="article-meta__item">
            <span class="article-meta__label">Published</span>
            <time class="article-meta__value" datetime="{html.escape(pub_raw, quote=True)}">{html.escape(pub_display)}</time>
          </div>

          <div class="article-meta__item">
            <span class="article-meta__label">Posted to WTK</span>
            <time class="article-meta__value" datetime="{html.escape(posted, quote=True)}">{html.escape(posted)}</time>
          </div>

          <div class="article-meta__item">
            <span class="article-meta__label">Curation Rank</span>
            <span class="article-meta__value">{html.escape(priority)}</span>
          </div>

          <div class="article-meta__item">
            <span class="article-meta__label">Article ID</span>
            <span class="article-meta__value">{html.escape(aid)}</span>
          </div>
        </div>
      </div>
    </header>

    <section class="article-content-shell">
      <div class="{layout_class}">
        <article class="article-main">

          <div class="article-body">
            {summary}
          </div>

          {note_block}


          <section
            class="article-latest"
            aria-labelledby="article-latest-title"
          >

            <header class="article-latest__heading">

              <p class="eyebrow">
                Latest
              </p>

              <h2 id="article-latest-title">
                <a
                class="article-latest__link"
                href="/news/latest.html"
                >
                  Latest News
                </a>
              </h2>

            </header>


            <wtk-news-feed
              class="article-latest__feed"
              limit="4"
              sort="newest"
              hide-sort
              hide-count
              aria-label="Latest news"
            >
            </wtk-news-feed>

          </section>


          <section
            class="article-procedure"
            aria-labelledby="article-procedure-title"
          >

            <h2 id="article-procedure-title">
              {html.escape(PROCEDURE_HEADING)}
            </h2>

            <p>
              {html.escape(PROCEDURE_TEXT)}
            </p>

          </section>

        </article>


        {related_block}
      </div>
    </section>

  </main>

  <div id="global-footer" data-global-footer></div>

  <script src="/assets/js/global.js" defer></script>
  <script type="module" src="/assets/js/components/news-feed.js"></script>
</body>
</html>
'''

def main():
    a = args()

    for path in (MASTER, INDEX, CATEGORY_MAP):
        if not path.exists():
            raise FileNotFoundError(path)

    articles = load_jsonl(MASTER)
    index_rows = load_jsonl(INDEX)
    labels = load_labels()

    index_by_id = {
        str(row.get("id")): row
        for row in index_rows
        if row.get("id") is not None
    }

    if a.all:
        selected = articles
    elif a.id:
        selected = [x for x in articles if str(x.get("article_id")) == str(a.id)]
    else:
        selected = [x for x in articles if str(x.get("slug")) == str(a.slug)]

    if not selected:
        raise SystemExit("No matching article found.")

    if not a.all and len(selected) != 1:
        raise SystemExit(f"Expected one article, found {len(selected)}.")

    NEWS.mkdir(parents=True, exist_ok=True)

    generated = 0
    for article in selected:
        slug = str(article.get("slug") or "").strip()
        aid = str(article.get("article_id") or "").strip()

        if not slug:
            print(f"SKIP {aid}: missing slug")
            continue

        out = NEWS / f"{slug}.html"
        out.write_text(page(article, index_by_id, labels), encoding="utf-8", newline="\n")
        generated += 1
        print(f"{aid:>6}  /news/{slug}.html")

    print(f"\nGenerated {generated:,} article page{'s' if generated != 1 else ''}.")


if __name__ == "__main__":
    main()
