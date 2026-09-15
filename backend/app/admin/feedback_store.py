from __future__ import annotations

from collections import deque
import json
import os
from pathlib import Path
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
            envelope = json.loads(raw)

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

            record = dict(record)

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

    return {
        "records": records,
        "total": total,
        "loaded": len(records),
        "errors": errors,
    }


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
            record = json.loads(raw)

            if not isinstance(
                record,
                dict,
            ):
                raise ValueError(
                    "Survey record is not an object"
                )

            record = dict(record)

            record["_line_number"] = (
                line_number
            )

            records.append(
                record
            )

        except Exception:
            errors += 1

    return {
        "records": records,
        "total": total,
        "loaded": len(records),
        "errors": errors,
    }
