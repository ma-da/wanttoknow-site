from __future__ import annotations

import os
import re
import sqlite3
import threading

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field


router = APIRouter()


# ============================================================================
# Configuration
# ============================================================================

DEFAULT_PAGEVIEW_DB = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "private"
    / "pageviews.sqlite"
)

PAGEVIEW_DB = Path(
    os.getenv(
        "WTK_PAGEVIEW_DB",
        str(DEFAULT_PAGEVIEW_DB),
    )
)


# ============================================================================
# Request model
# ============================================================================

class PageviewRequest(BaseModel):
    path: str = Field(
        min_length=1,
        max_length=1024,
    )


# ============================================================================
# Database
# ============================================================================

_db_initialized = False
_db_lock = threading.Lock()


def initialize_database() -> None:
    global _db_initialized

    if _db_initialized:
        return

    with _db_lock:
        if _db_initialized:
            return

        PAGEVIEW_DB.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        connection = sqlite3.connect(
            PAGEVIEW_DB,
            timeout=5.0,
        )

        try:
            connection.execute(
                "PRAGMA journal_mode=WAL"
            )

            connection.execute(
                "PRAGMA busy_timeout=5000"
            )

            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pageview_daily (
                    path TEXT NOT NULL,
                    view_date TEXT NOT NULL,
                    views INTEGER NOT NULL DEFAULT 0,
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY (
                        path,
                        view_date
                    )
                )
                """
            )

            connection.commit()

        finally:
            connection.close()

        _db_initialized = True


def increment_pageview(
    path: str,
) -> None:
    initialize_database()

    now = datetime.now(
        timezone.utc
    )

    timestamp = (
        now.isoformat(
            timespec="seconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )

    day = now.date().isoformat()

    connection = sqlite3.connect(
        PAGEVIEW_DB,
        timeout=5.0,
    )

    try:
        connection.execute(
            "PRAGMA busy_timeout=5000"
        )

        connection.execute(
            """
            INSERT INTO pageview_daily (
                path,
                view_date,
                views,
                last_seen_at
            )
            VALUES (?, ?, 1, ?)

            ON CONFLICT (
                path,
                view_date
            )
            DO UPDATE SET
                views = views + 1,
                last_seen_at = excluded.last_seen_at
            """,
            (
                path,
                day,
                timestamp,
            ),
        )

        connection.commit()

    finally:
        connection.close()


# ============================================================================
# Path validation
# ============================================================================

def normalize_path(
    raw_path: str,
) -> str | None:

    path = raw_path.strip()

    if not path.startswith("/"):
        return None

    if (
        "\x00" in path
        or "\n" in path
        or "\r" in path
        or "?" in path
        or "#" in path
        or "://" in path
    ):
        return None

    path = re.sub(
        r"/{2,}",
        "/",
        path,
    )

    if len(path) > 1:
        path = path.rstrip("/")

    if path.startswith(
        (
            "/admin",
            "/api/",
            "/assets/",
        )
    ):
        return None

    return path or "/"


# ============================================================================
# Endpoint
# ============================================================================

@router.post(
    "/api/pageview",
    status_code=204,
)
def record_pageview(
    payload: PageviewRequest,
    request: Request,
) -> Response:

    path = normalize_path(
        payload.path
    )

    if path is None:
        return Response(
            status_code=204
        )

    increment_pageview(
        path
    )

    return Response(
        status_code=204
    )