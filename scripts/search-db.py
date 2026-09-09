#!/usr/bin/env python3
"""
Simple CLI smoke-test for WantToKnow.info SQLite FTS5 search.

Examples
--------
python scripts/search-db.py "CIA mind control"
python scripts/search-db.py "surveillance" --family news
python scripts/search-db.py '"remote viewing"' --limit 20
python scripts/search-db.py "artificial intelligence" --family document
python scripts/search-db.py "mind control" --publisher "WTK Page"
python scripts/search-db.py "transformation" --publisher "PEERS Substack"
"""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import re
import sqlite3
import sys


DEFAULT_DB = Path(
    "/mnt/c/datasources/wanttoknow-site/"
    "src/site/data/search/wanttoknow-search.sqlite"
)

TOKEN_RE = re.compile(r"[^\s]+")


def safe_fts_query(text: str) -> str:
    """
    Turn ordinary user text into an AND query of quoted tokens.

    This avoids most accidental FTS5 syntax errors while still allowing
    straightforward lexical testing. Use --raw to supply native FTS5 syntax.
    """
    tokens = [
        token.strip()
        for token in TOKEN_RE.findall(
            text
        )
        if token.strip()
    ]

    return " AND ".join(
        '"'
        + token.replace(
            '"',
            '""',
        )
        + '"'
        for token in tokens
    )


def args():
    parser = ArgumentParser()

    parser.add_argument(
        "query",
    )

    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=10,
    )

    parser.add_argument(
        "--family",
        choices=[
            "news",
            "document",
            "youtube",
        ],
    )

    parser.add_argument(
        "--record-type",
        choices=[
            "news",
            "page_chunk",
            "substack_chunk",
            "youtube_chunk",
        ],
    )

    parser.add_argument(
        "--publisher",
        help=(
            "Exact publisher filter, e.g. "
            "'WTK Page', 'PEERS Substack', "
            "or 'PEERS Conscious Media'."
        ),
    )

    parser.add_argument(
        "--raw",
        action="store_true",
        help="Treat query as native FTS5 MATCH syntax.",
    )

    return parser.parse_args()


def main():
    a = args()

    if not a.db.exists():
        raise FileNotFoundError(
            f"Search database not found: {a.db}"
        )

    query = (
        a.query
        if a.raw
        else safe_fts_query(
            a.query
        )
    )

    if not query:
        raise RuntimeError(
            "Query contains no searchable terms."
        )

    where = [
        "fts_content MATCH ?",
    ]

    params = [
        query,
    ]

    if a.family:
        where.append(
            "c.family = ?"
        )

        params.append(
            a.family
        )

    if a.record_type:
        where.append(
            "c.record_type = ?"
        )

        params.append(
            a.record_type
        )

    if a.publisher:
        where.append(
            "c.publisher = ? COLLATE NOCASE"
        )

        params.append(
            a.publisher
        )

    params.append(
        max(
            1,
            a.limit,
        )
    )

    sql = f"""
        SELECT
            c.ref_id,
            c.family,
            c.record_type,
            c.title,
            c.url,
            c.published_at,
            c.publisher,
            c.section,
            c.topic,
            c.priority,
            bm25(
                fts_content,
                5.0,  -- title
                1.0,  -- text
                2.0,  -- publisher
                2.5   -- topics
            ) AS score,
            snippet(
                fts_content,
                1,
                '[',
                ']',
                ' … ',
                24
            ) AS snippet
        FROM fts_content
        JOIN content AS c
            ON c.ref_id = fts_content.rowid
        WHERE {" AND ".join(where)}
        ORDER BY
            score ASC,
            COALESCE(c.priority, 0) DESC,
            c.ref_id ASC
        LIMIT ?
    """

    connection = sqlite3.connect(
        a.db
    )

    connection.row_factory = sqlite3.Row

    try:
        rows = connection.execute(
            sql,
            params,
        ).fetchall()

    finally:
        connection.close()

    print()
    print(
        f"FTS query: {query}"
    )
    print(
        f"Results:   {len(rows)}"
    )
    print()

    for rank, row in enumerate(
        rows,
        1,
    ):
        print(
            f"{rank:>2}. "
            f"ref {row['ref_id']} | "
            f"{row['family']} | "
            f"{row['record_type']} | "
            f"score {row['score']:.6f}"
        )

        print(
            f"    {row['title']}"
        )

        if row[
            "publisher"
        ]:
            print(
                f"    {row['publisher']}"
            )

        if row[
            "url"
        ]:
            print(
                f"    {row['url']}"
            )

        if row[
            "snippet"
        ]:
            print(
                f"    {row['snippet']}"
            )

        print()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        raise

    except Exception as exc:
        print(
            f"\nSEARCH FAILED\n{exc}",
            file=sys.stderr,
        )

        raise