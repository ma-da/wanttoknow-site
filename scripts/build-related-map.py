#!/usr/bin/env python3
"""Build WantToKnow.info TF-IDF related-content map.

Output format
-------------
{
  "1": [123, 456, ... 24 ids total],
  "2": [...],
  ...
}

The source SQLite database is derived search data. The related map is also a
fully derived artifact and can be regenerated whenever the search corpus changes.

Default similarity document
---------------------------
title + normalized topics/tags + searchable text

TF-IDF settings
---------------
* lowercase
* English stop words
* unigrams + bigrams
* min_df=2
* max_df=0.98
* sublinear term frequency
* L2 normalization

By default, chunks from the same underlying source_id/family are excluded from
one another. This prevents adjacent page or video chunks from dominating every
related list. Use --include-same-source to disable that behavior.
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json
import sqlite3
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


ROOT = Path("/mnt/c/datasources/wanttoknow-site")
DEFAULT_DB = ROOT / "src/site/data/search/wanttoknow-search.sqlite"
DEFAULT_OUTPUT = ROOT / "src/site/data/search/related-content.json"


def args():
    parser = ArgumentParser(
        description="Build exact top-N TF-IDF related references."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--neighbors", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--max-features", type=int, default=200_000)
    parser.add_argument(
        "--include-same-source",
        action="store_true",
        help="Allow chunks from the same family/source_id to recommend each other.",
    )
    return parser.parse_args()


def load_rows(db_path: Path) -> list[sqlite3.Row]:
    if not db_path.is_file():
        raise FileNotFoundError(f"Search database not found: {db_path}")

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            """
            SELECT
                ref_id,
                family,
                record_type,
                source_id,
                title,
                topics,
                text
            FROM content
            ORDER BY ref_id ASC
            """
        ).fetchall()
    finally:
        connection.close()

    if len(rows) < 2:
        raise RuntimeError("Need at least two content rows to build related content.")

    return rows


def document_text(row: sqlite3.Row) -> str:
    parts = [
        str(row["title"] or "").strip(),
        str(row["topics"] or "").strip(),
        str(row["text"] or "").strip(),
    ]
    return "\n".join(part for part in parts if part)


def source_group(row: sqlite3.Row) -> tuple[str, str]:
    return (
        str(row["family"] or ""),
        str(row["source_id"] or ""),
    )


def build_map(
    rows: list[sqlite3.Row],
    *,
    neighbors: int,
    batch_size: int,
    max_features: int,
    include_same_source: bool,
) -> tuple[dict[str, list[int]], int]:
    if neighbors < 1:
        raise ValueError("--neighbors must be at least 1")

    if batch_size < 1:
        raise ValueError("--batch-size must be at least 1")

    ref_ids = np.asarray([int(row["ref_id"]) for row in rows], dtype=np.int64)
    texts = [document_text(row) for row in rows]

    vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        stop_words="english",
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.98,
        sublinear_tf=True,
        norm="l2",
        dtype=np.float32,
        max_features=max_features,
    )

    print("Vectorizing unified corpus...")
    matrix = vectorizer.fit_transform(texts)

    if matrix.shape[1] == 0:
        raise RuntimeError("TF-IDF vocabulary is empty.")

    print(f"Rows:       {matrix.shape[0]:,}")
    print(f"Features:   {matrix.shape[1]:,}")
    print(f"Neighbors:  {neighbors}")

    group_members: dict[tuple[str, str], list[int]] = {}
    if not include_same_source:
        for index, row in enumerate(rows):
            group_members.setdefault(source_group(row), []).append(index)

    result: dict[str, list[int]] = {}
    row_count = len(rows)
    target_count = min(neighbors, row_count - 1)

    for start in range(0, row_count, batch_size):
        end = min(start + batch_size, row_count)
        similarities = linear_kernel(
            matrix[start:end],
            matrix,
            dense_output=True,
        )

        for local_index, global_index in enumerate(range(start, end)):
            scores = similarities[local_index]
            scores[global_index] = -np.inf

            if not include_same_source:
                for excluded_index in group_members[source_group(rows[global_index])]:
                    scores[excluded_index] = -np.inf

            valid_count = int(np.isfinite(scores).sum())
            if valid_count < target_count:
                raise RuntimeError(
                    f"Ref {ref_ids[global_index]} has only {valid_count} eligible "
                    f"neighbors; need {target_count}."
                )

            candidate_indexes = np.argpartition(
                scores,
                -target_count,
            )[-target_count:]

            ranked = sorted(
                candidate_indexes.tolist(),
                key=lambda idx: (
                    -float(scores[idx]),
                    int(ref_ids[idx]),
                ),
            )

            result[str(int(ref_ids[global_index]))] = [
                int(ref_ids[idx])
                for idx in ranked[:target_count]
            ]

        print(f"Processed {end:,} / {row_count:,}", end="\r", flush=True)

    print()
    return result, matrix.shape[1]


def validate_map(
    related: dict[str, list[int]],
    ref_ids: set[int],
    expected_neighbors: int,
) -> None:
    if len(related) != len(ref_ids):
        raise RuntimeError(
            f"Map has {len(related)} keys but corpus has {len(ref_ids)} refs."
        )

    for key, values in related.items():
        ref_id = int(key)

        if len(values) != expected_neighbors:
            raise RuntimeError(
                f"Ref {ref_id} has {len(values)} neighbors; "
                f"expected {expected_neighbors}."
            )

        if len(set(values)) != len(values):
            raise RuntimeError(f"Ref {ref_id} has duplicate related IDs.")

        if ref_id in values:
            raise RuntimeError(f"Ref {ref_id} relates to itself.")

        missing = [value for value in values if value not in ref_ids]
        if missing:
            raise RuntimeError(
                f"Ref {ref_id} contains unknown related IDs: {missing[:10]}"
            )


def main() -> None:
    a = args()
    rows = load_rows(a.db)

    related, feature_count = build_map(
        rows,
        neighbors=a.neighbors,
        batch_size=a.batch_size,
        max_features=a.max_features,
        include_same_source=a.include_same_source,
    )

    expected_neighbors = min(a.neighbors, len(rows) - 1)
    validate_map(
        related,
        {int(row["ref_id"]) for row in rows},
        expected_neighbors,
    )

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(
        json.dumps(
            related,
            ensure_ascii=False,
            indent=2,
            sort_keys=False,
        ) + "\n",
        encoding="utf-8",
    )

    print(f"Wrote:      {a.output}")
    print(f"Map rows:   {len(related):,}")
    print(f"Features:   {feature_count:,}")
    print("Validation: OK")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(f"\nRELATED MAP BUILD FAILED\n{exc}", file=sys.stderr)
        raise
