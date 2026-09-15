from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo

from fastapi import (
    APIRouter,
    Depends,
    Query,
)

from .auth import (
    AdminIdentity,
    require_admin_api,
)


router = APIRouter(
    tags=["admin-analytics"],
)

PAGEVIEW_DB = Path(
    os.getenv(
        "WTK_PAGEVIEW_DB",
        "/srv/wanttoknow/data/analytics/pageviews.sqlite",
    )
)


@router.get(
    "/api/admin/analytics/pages",
)
def recent_pages(
    identity: AdminIdentity = Depends(
        require_admin_api
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=100,
    ),
):
    today = (
        datetime.now(
            ZoneInfo(
                "America/Chicago"
            )
        )
        .date()
        .isoformat()
    )

    with sqlite3.connect(
        str(PAGEVIEW_DB),
        timeout=5,
    ) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT
                path,

                SUM(
                    CASE
                        WHEN view_date = ?
                        THEN views
                        ELSE 0
                    END
                ) AS daily_visits,

                SUM(views) AS total_visits,

                MAX(last_seen_at) AS last_seen_at

            FROM pageview_daily

            GROUP BY path

            HAVING SUM(views) >= 1

            ORDER BY
                last_seen_at DESC

            LIMIT ?
            """,
            (
                today,
                limit,
            ),
        ).fetchall()

        totals = conn.execute(
            """
            SELECT
                SUM(
                    CASE
                        WHEN view_date = ?
                        THEN views
                        ELSE 0
                    END
                ) AS daily_total,

                SUM(views) AS grand_total

            FROM pageview_daily
            """,
            (today,),
        ).fetchone()

    return {
        "daily_total": (
            totals["daily_total"]
            if totals
            and totals["daily_total"] is not None
            else 0
        ),

        "grand_total": (
            totals["grand_total"]
            if totals
            and totals["grand_total"] is not None
            else 0
        ),

        "records": [
            {
                "path": row["path"],

                "daily_visits": (
                    row["daily_visits"]
                    or 0
                ),

                "total_visits": (
                    row["total_visits"]
                    or 0
                ),

                "last_seen_at": (
                    row["last_seen_at"]
                ),
            }
            for row in rows
        ],
    }
