from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

from app.services.crypto import decrypt_json


CONTACT_PURPOSE = "contact-submission"

DEFAULT_CONTACT_FILE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "private"
    / "contact-submissions.jsonl"
)

CONTACT_FILE = Path(
    os.getenv(
        "WTK_CONTACT_FILE",
        str(DEFAULT_CONTACT_FILE),
    )
)

SURVEY_FILE = Path(
    os.getenv(
        "WTK_SURVEY_FILE",
        "/var/lib/wanttoknow/feedback/site-feedback.jsonl",
    )
)

ADMIN_FEEDBACK_DB = Path(
    os.getenv(
        "WTK_ADMIN_FEEDBACK_DB",
        "/srv/wanttoknow/data/admin/feedback-admin.sqlite",
    )
)

VALID_SOURCES = {
    "contact",
    "survey",
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(
            timespec="seconds"
        )
        .replace(
            "+00:00",
            "Z",
        )
    )


def _tail_jsonl(
    path: Path,
    limit: int,
) -> tuple[list[tuple[int, str]], int]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Feedback file not found: {path}"
        )

    kept: deque[tuple[int, str]] = deque(
        maxlen=limit
    )

    total = 0

    with path.open(
        "r",
        encoding="utf-8",
    ) as handle:
        for line_number, raw in enumerate(
            handle,
            start=1,
        ):
            raw = raw.strip()

            if not raw:
                continue

            total += 1

            kept.append(
                (
                    line_number,
                    raw,
                )
            )

    return list(reversed(kept)), total


# ============================================================================
# Admin metadata
# ============================================================================

def _connect_admin_db() -> sqlite3.Connection:
    conn = sqlite3.connect(
        str(ADMIN_FEEDBACK_DB),
        timeout=10,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA busy_timeout = 5000"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS feedback_admin_meta (
            source TEXT NOT NULL,
            record_key TEXT NOT NULL,

            is_read INTEGER NOT NULL
                DEFAULT 0
                CHECK (is_read IN (0, 1)),

            is_archived INTEGER NOT NULL
                DEFAULT 0
                CHECK (is_archived IN (0, 1)),

            internal_note TEXT NOT NULL
                DEFAULT '',

            updated_at TEXT NOT NULL,
            updated_by TEXT NOT NULL,

            PRIMARY KEY (
                source,
                record_key
            )
        )
        """
    )

    return conn


def _default_admin_state() -> dict[str, Any]:
    return {
        "is_read": False,
        "is_archived": False,
        "internal_note": "",
        "updated_at": None,
        "updated_by": None,
    }


def _load_admin_states(
    source: str,
) -> dict[str, dict[str, Any]]:
    if source not in VALID_SOURCES:
        raise ValueError(
            f"Unknown feedback source: {source}"
        )

    with _connect_admin_db() as conn:
        rows = conn.execute(
            """
            SELECT
                record_key,
                is_read,
                is_archived,
                internal_note,
                updated_at,
                updated_by
            FROM feedback_admin_meta
            WHERE source = ?
            """,
            (source,),
        ).fetchall()

    states: dict[str, dict[str, Any]] = {}

    for row in rows:
        states[str(row["record_key"])] = {
            "is_read": bool(
                row["is_read"]
            ),
            "is_archived": bool(
                row["is_archived"]
            ),
            "internal_note": (
                row["internal_note"]
                or ""
            ),
            "updated_at": (
                row["updated_at"]
            ),
            "updated_by": (
                row["updated_by"]
            ),
        }

    return states


def _attach_admin_states(
    source: str,
    records: list[dict[str, Any]],
) -> None:
    states = _load_admin_states(
        source
    )

    for record in records:
        record_key = str(
            record["_line_number"]
        )

        record["_record_key"] = (
            record_key
        )

        record["_admin"] = states.get(
            record_key,
            _default_admin_state(),
        )


def update_feedback_admin_state(
    source: str,
    record_key: str,
    *,
    is_read: bool | None = None,
    is_archived: bool | None = None,
    internal_note: str | None = None,
    updated_by: str = "admin",
) -> dict[str, Any]:
    if source not in VALID_SOURCES:
        raise ValueError(
            f"Unknown feedback source: {source}"
        )

    record_key = str(
        record_key
    ).strip()

    if not record_key:
        raise ValueError(
            "Missing feedback record key."
        )

    with _connect_admin_db() as conn:
        row = conn.execute(
            """
            SELECT
                is_read,
                is_archived,
                internal_note
            FROM feedback_admin_meta
            WHERE
                source = ?
                AND record_key = ?
            """,
            (
                source,
                record_key,
            ),
        ).fetchone()

        if row is None:
            current_read = False
            current_archived = False
            current_note = ""

        else:
            current_read = bool(
                row["is_read"]
            )
            current_archived = bool(
                row["is_archived"]
            )
            current_note = (
                row["internal_note"]
                or ""
            )

        new_read = (
            current_read
            if is_read is None
            else bool(is_read)
        )

        new_archived = (
            current_archived
            if is_archived is None
            else bool(is_archived)
        )

        new_note = (
            current_note
            if internal_note is None
            else internal_note.strip()
        )

        updated_at = _utc_now()

        conn.execute(
            """
            INSERT INTO feedback_admin_meta (
                source,
                record_key,
                is_read,
                is_archived,
                internal_note,
                updated_at,
                updated_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)

            ON CONFLICT (
                source,
                record_key
            )
            DO UPDATE SET
                is_read = excluded.is_read,
                is_archived = excluded.is_archived,
                internal_note = excluded.internal_note,
                updated_at = excluded.updated_at,
                updated_by = excluded.updated_by
            """,
            (
                source,
                record_key,
                int(new_read),
                int(new_archived),
                new_note,
                updated_at,
                updated_by,
            ),
        )

    return {
        "is_read": new_read,
        "is_archived": new_archived,
        "internal_note": new_note,
        "updated_at": updated_at,
        "updated_by": updated_by,
    }


# ============================================================================
# Contact submissions
# ============================================================================

def load_contacts(
    limit: int = 250,
) -> dict[str, Any]:
    lines, total = _tail_jsonl(
        CONTACT_FILE,
        limit,
    )

    records: list[dict[str, Any]] = []
    errors = 0

    for line_number, raw in lines:
        try:
            envelope = json.loads(
                raw
            )

            if not isinstance(
                envelope,
                dict,
            ):
                raise ValueError(
                    "Encrypted record is not an object"
                )

            record = decrypt_json(
                envelope,
                expected_purpose=CONTACT_PURPOSE,
            )

            if not isinstance(
                record,
                dict,
            ):
                raise ValueError(
                    "Contact record is not an object"
                )

            record = dict(
                record
            )

            record["_line_number"] = (
                line_number
            )

            records.append(
                record
            )

        except Exception:
            # Do not expose crypto details or
            # malformed private records to the client.
            errors += 1

    _attach_admin_states(
        "contact",
        records,
    )

    return {
        "records": records,
        "total": total,
        "loaded": len(records),
        "errors": errors,
    }


# ============================================================================
# Survey responses
# ============================================================================

def load_surveys(
    limit: int = 250,
) -> dict[str, Any]:
    lines, total = _tail_jsonl(
        SURVEY_FILE,
        limit,
    )

    records: list[dict[str, Any]] = []
    errors = 0

    for line_number, raw in lines:
        try:
            record = json.loads(
                raw
            )

            if not isinstance(
                record,
                dict,
            ):
                raise ValueError(
                    "Survey record is not an object"
                )

            record = dict(
                record
            )

            record["_line_number"] = (
                line_number
            )

            records.append(
                record
            )

        except Exception:
            errors += 1

    _attach_admin_states(
        "survey",
        records,
    )

    return {
        "records": records,
        "total": total,
        "loaded": len(records),
        "errors": errors,
    }
