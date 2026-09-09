#!/usr/bin/env python3

"""
Build derived WantToKnow.info NEWS artifacts from the canonical article master.

INPUT
-----
src/site/data/wtk_articles_master.jsonl

OUTPUTS
-------
src/site/data/article-related-24.json
src/site/data/article-related-24-with-scores.json
src/site/data/article-index.jsonl
src/site/data/archive_stats.json

This builder handles NEWS-to-NEWS TF-IDF relationships only.

It deliberately does NOT build:
    src/site/data/search/related-content.json

That broader whole-site/chunk relationship map is generated separately.

The canonical master is never modified.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import json
import os
import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


# ============================================================================
# Configuration
# ============================================================================

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "src" / "site" / "data"

MASTER = DATA / "wtk_articles_master.jsonl"

RELATED_24 = DATA / "article-related-24.json"
RELATED_24_SCORES = DATA / "article-related-24-with-scores.json"
ARTICLE_INDEX = DATA / "article-index.jsonl"
ARCHIVE_STATS = DATA / "archive_stats.json"

TOP_RELATED = 24
INDEX_RELATED = 12
BATCH_SIZE = 256


# ============================================================================
# Helpers
# ============================================================================

def clean(value) -> str:
    if value is None:
        return ""

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()


def read_master() -> list[dict]:
    if not MASTER.is_file():
        raise FileNotFoundError(
            f"Canonical master not found: {MASTER}"
        )

    records = []

    with MASTER.open(
        "r",
        encoding="utf-8",
    ) as f:

        for line_number, line in enumerate(
            f,
            start=1,
        ):
            if not line.strip():
                continue

            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSON in {MASTER} "
                    f"at line {line_number}: {exc}"
                ) from exc

            records.append(record)

    if not records:
        raise RuntimeError(
            "Canonical article master contains no records."
        )

    return records


def normalize_id(value) -> int:
    try:
        return int(str(value).strip())
    except Exception as exc:
        raise ValueError(
            f"Invalid article ID: {value!r}"
        ) from exc


def normalize_priority(value):
    if value is None or value == "":
        return None

    try:
        return int(float(value))
    except Exception as exc:
        raise ValueError(
            f"Invalid priority: {value!r}"
        ) from exc


def normalize_tags(value) -> list[str]:
    if value is None:
        return []

    if not isinstance(value, list):
        raise ValueError(
            f"tags must be a list, got {type(value).__name__}"
        )

    return [
        clean(tag)
        for tag in value
        if clean(tag)
    ]


def build_tfidf_input(article: dict) -> str:
    """
    Match the migration notebook's news-similarity model:

        title
        publication date
        publication display name
        summary
    """

    title = clean(
        article.get("title")
    )

    date = clean(
        article.get("publication_date")
    )

    publication = clean(
        article.get("publication_name")
        or article.get("publication_group")
    )

    summary = clean(
        article.get("summary_markdown")
    )

    return clean(
        f"{title} "
        f"as reported on {date} "
        f"by {publication}. "
        f"{summary}"
    )


def valid_iso_date(value: str):
    value = clean(value)

    if not value:
        return None

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d",
        )
    except ValueError:
        return None


def write_json_temp(
    path: Path,
    obj,
    *,
    indent=None,
):
    tmp = path.with_name(
        path.name + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:
        json.dump(
            obj,
            f,
            ensure_ascii=False,
            indent=indent,
            separators=None if indent else (",", ":"),
        )
        f.write("\n")

    return tmp


def write_jsonl_temp(
    path: Path,
    records: list[dict],
):
    tmp = path.with_name(
        path.name + ".tmp"
    )

    with tmp.open(
        "w",
        encoding="utf-8",
        newline="\n",
    ) as f:

        for record in records:
            f.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            )
            f.write("\n")

    return tmp


# ============================================================================
# Load and validate canonical master
# ============================================================================

articles = read_master()

article_ids = [
    normalize_id(
        article.get("article_id")
    )
    for article in articles
]

if len(article_ids) != len(set(article_ids)):
    duplicates = [
        aid
        for aid, count
        in Counter(article_ids).items()
        if count > 1
    ]

    raise RuntimeError(
        "Duplicate article IDs: "
        + ", ".join(
            str(x)
            for x in sorted(duplicates)[:20]
        )
    )


slugs = [
    clean(article.get("slug"))
    for article in articles
]

if any(not slug for slug in slugs):
    raise RuntimeError(
        "One or more articles have blank slugs."
    )

if len(slugs) != len(set(slugs)):
    duplicates = [
        slug
        for slug, count
        in Counter(slugs).items()
        if count > 1
    ]

    raise RuntimeError(
        "Duplicate article slugs: "
        + ", ".join(
            sorted(duplicates)[:20]
        )
    )


print("=" * 72)
print("WantToKnow.info NEWS derived build")
print("=" * 72)
print()
print(
    "Canonical articles:",
    f"{len(articles):,}"
)


# ============================================================================
# Build TF-IDF matrix
# ============================================================================

texts = [
    build_tfidf_input(article)
    for article in articles
]


vectorizer = TfidfVectorizer(
    lowercase=True,
    stop_words="english",
    ngram_range=(1, 2),
    min_df=2,
    max_df=0.95,
    sublinear_tf=True,
    token_pattern=(
        r"(?u)\b"
        r"[a-zA-Z0-9]"
        r"[a-zA-Z0-9'-]+"
        r"\b"
    ),
    dtype=np.float32,
)


tfidf_matrix = vectorizer.fit_transform(
    texts
)


print()
print(
    "TF-IDF matrix:",
    tfidf_matrix.shape,
)

print(
    "Nonzero values:",
    f"{tfidf_matrix.nnz:,}",
)

print(
    "Features:",
    f"{len(vectorizer.get_feature_names_out()):,}",
)


# ============================================================================
# Calculate top-24 NEWS relationships
# ============================================================================

related_24: dict[str, list[int]] = {}
related_24_scores: dict[str, list[dict]] = {}

article_ids_array = np.asarray(
    article_ids,
    dtype=np.int64,
)

count = len(articles)
top_count = min(
    TOP_RELATED,
    max(0, count - 1),
)


for batch_start in range(
    0,
    count,
    BATCH_SIZE,
):

    batch_end = min(
        batch_start + BATCH_SIZE,
        count,
    )

    similarity_block = linear_kernel(
        tfidf_matrix[
            batch_start:batch_end
        ],
        tfidf_matrix,
    )


    for local_i in range(
        batch_end - batch_start
    ):

        global_i = (
            batch_start
            + local_i
        )

        article_id = int(
            article_ids_array[
                global_i
            ]
        )


        if top_count == 0:
            related_24[
                str(article_id)
            ] = []

            related_24_scores[
                str(article_id)
            ] = []

            continue


        scores = similarity_block[
            local_i
        ].copy()

        # Never return the source article.
        scores[
            global_i
        ] = -1.0


        candidate_indices = (
            np.argpartition(
                scores,
                -top_count,
            )[-top_count:]
        )


        # Descending similarity.
        # Article ID is a deterministic tie breaker
        # within the candidate set.
        candidate_indices = sorted(
            candidate_indices,
            key=lambda index: (
                -float(scores[index]),
                int(
                    article_ids_array[
                        index
                    ]
                ),
            ),
        )


        related_ids = [
            int(
                article_ids_array[
                    index
                ]
            )
            for index in candidate_indices
        ]


        related_scores = [
            {
                "article_id":
                    int(
                        article_ids_array[
                            index
                        ]
                    ),

                "similarity":
                    round(
                        float(
                            scores[index]
                        ),
                        6,
                    ),
            }

            for index in candidate_indices
        ]


        related_24[
            str(article_id)
        ] = related_ids

        related_24_scores[
            str(article_id)
        ] = related_scores


    print(
        f"Related-news TF-IDF: "
        f"{batch_end:,} / {count:,}"
    )


# ============================================================================
# Build compact browser article index
# ============================================================================

article_index = []

valid_ids = set(article_ids)


for article in articles:

    article_id = normalize_id(
        article.get("article_id")
    )

    related = (
        related_24[
            str(article_id)
        ][:INDEX_RELATED]
    )


    record = {
        "date":
            clean(
                article.get(
                    "publication_date"
                )
            ),

        "posted_date":
            clean(
                article.get(
                    "posted_date"
                )
            ),

        "id":
            article_id,

        "priority":
            normalize_priority(
                article.get(
                    "priority"
                )
            ),

        "publisher":
            clean(
                article.get(
                    "publication_group"
                )
            ),

        "related":
            related,

        "slug":
            clean(
                article.get(
                    "slug"
                )
            ),

        "tags":
            normalize_tags(
                article.get(
                    "tags"
                )
            ),

        "title":
            clean(
                article.get(
                    "title"
                )
            ),
    }


    for related_id in related:
        if related_id not in valid_ids:
            raise RuntimeError(
                f"Article {article_id} has "
                f"invalid related ID "
                f"{related_id}"
            )


    article_index.append(
        record
    )


# ============================================================================
# Build archive statistics
# ============================================================================

category_counter = Counter()
publisher_counter = Counter()
publisher_names = {}

year_counter = Counter()

dated = []
undated_count = 0
articles_with_images = 0
articles_with_related = 0


for article, index_record in zip(
    articles,
    article_index,
):

    tags = normalize_tags(
        article.get("tags")
    )

    category_counter.update(
        tags
    )


    publisher = clean(
        article.get(
            "publication_group"
        )
    )

    if publisher:
        publisher_counter[
            publisher
        ] += 1

        publisher_names.setdefault(
            publisher,
            clean(
                article.get(
                    "publication_name"
                )
            )
            or publisher,
        )


    parsed_date = valid_iso_date(
        article.get(
            "publication_date"
        )
    )

    if parsed_date is None:
        undated_count += 1

    else:
        dated.append(
            parsed_date
        )

        year_counter[
            parsed_date.year
        ] += 1


    if clean(
        article.get(
            "image_filename"
        )
    ):
        articles_with_images += 1


    if index_record[
        "related"
    ]:
        articles_with_related += 1


category_items = sorted(
    category_counter.items(),
    key=lambda item: (
        -item[1],
        item[0],
    ),
)

publisher_items = sorted(
    publisher_counter.items(),
    key=lambda item: (
        -item[1],
        item[0],
    ),
)


archive_stats = {
    "article_count":
        len(articles),

    "date_range": {
        "first":
            min(dated).strftime(
                "%Y-%m-%d"
            )
            if dated
            else None,

        "last":
            max(dated).strftime(
                "%Y-%m-%d"
            )
            if dated
            else None,
    },

    "dated_article_count":
        len(dated),

    "undated_article_count":
        undated_count,

    "category_count":
        len(category_counter),

    "publisher_group_count":
        len(publisher_counter),

    "articles_with_images":
        articles_with_images,

    "articles_with_related":
        articles_with_related,

    "categories": {
        tag:
            count
        for tag, count
        in category_items
    },

    "publishing_groups": {
        slug: {
            "name":
                publisher_names.get(
                    slug,
                    slug,
                ),
            "count":
                count,
        }

        for slug, count
        in publisher_items
    },

    "articles_by_year": {
        str(year):
            year_counter[year]

        for year in sorted(
            year_counter
        )
    },
}


# ============================================================================
# Final validation before touching existing outputs
# ============================================================================

if len(article_index) != len(articles):
    raise RuntimeError(
        "Article-index record count mismatch."
    )

if len(related_24) != len(articles):
    raise RuntimeError(
        "Related-news map record count mismatch."
    )

if len(related_24_scores) != len(articles):
    raise RuntimeError(
        "Related-score map record count mismatch."
    )


for record in article_index:

    if len(
        record["related"]
    ) != min(
        INDEX_RELATED,
        max(
            0,
            len(articles) - 1,
        ),
    ):
        raise RuntimeError(
            f"Unexpected related count "
            f"for article {record['id']}"
        )


# ============================================================================
# Write all outputs to temporary files first
# ============================================================================

tmp_related = write_json_temp(
    RELATED_24,
    related_24,
    indent=2,
)

tmp_scores = write_json_temp(
    RELATED_24_SCORES,
    related_24_scores,
    indent=2,
)

tmp_index = write_jsonl_temp(
    ARTICLE_INDEX,
    article_index,
)

tmp_stats = write_json_temp(
    ARCHIVE_STATS,
    archive_stats,
    indent=2,
)


# ============================================================================
# Publish derived artifacts
# ============================================================================

for tmp, final in [
    (
        tmp_related,
        RELATED_24,
    ),
    (
        tmp_scores,
        RELATED_24_SCORES,
    ),
    (
        tmp_index,
        ARTICLE_INDEX,
    ),
    (
        tmp_stats,
        ARCHIVE_STATS,
    ),
]:
    os.replace(
        tmp,
        final,
    )


# ============================================================================
# Report
# ============================================================================

print()
print("=" * 72)
print("PASS — NEWS derived artifacts rebuilt")
print("=" * 72)

print(
    "Related-news records:",
    f"{len(related_24):,}",
)

print(
    "Index records:",
    f"{len(article_index):,}",
)

print(
    "Articles with 12 related:",
    f"{articles_with_related:,}",
)

print(
    "Categories:",
    f"{archive_stats['category_count']:,}",
)

print(
    "Publisher groups:",
    f"{archive_stats['publisher_group_count']:,}",
)

print(
    "Date range:",
    archive_stats["date_range"],
)

print()

for path in [
    RELATED_24,
    RELATED_24_SCORES,
    ARTICLE_INDEX,
    ARCHIVE_STATS,
]:
    print(
        f"{path.relative_to(ROOT)} "
        f"({path.stat().st_size / 1024 / 1024:.2f} MiB)"
    )
