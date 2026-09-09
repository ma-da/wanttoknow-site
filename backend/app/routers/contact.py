from __future__ import annotations

import fcntl
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.services.crypto import encrypt_json


router = APIRouter()


# ============================================================================
# Configuration
# ============================================================================

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


ALLOWED_CONTACT_TYPES = {
    "general",
    "story",
    "technical",
    "policy_legal",
}

ALLOWED_YES_NO = {
    "yes",
    "no",
}

CONTACT_ENCRYPTION_PURPOSE = (
    "contact-submission"
)


# ============================================================================
# Helpers
# ============================================================================

def clean_single_line(
    value: str,
    *,
    max_length: int,
) -> str:
    value = re.sub(
        r"\s+",
        " ",
        value.strip(),
    )

    return value[:max_length]


def clean_message(
    value: str,
    *,
    max_length: int = 6000,
) -> str:
    value = value.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    value = value.strip()

    return value[:max_length]


def valid_http_url(
    value: str,
) -> bool:
    if not value:
        return False

    try:
        parsed = urlparse(value)

        return (
            parsed.scheme in {"http", "https"}
            and bool(parsed.netloc)
        )

    except ValueError:
        return False


def valid_email(
    value: str,
) -> bool:
    """
    Lightweight validation.

    This is intentionally not trying to prove that
    the mailbox actually exists.
    """

    if len(value) > 254:
        return False

    return bool(
        re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            value,
        )
    )


def append_jsonl(
    record: dict,
) -> None:
    """
    Append exactly one JSON object as one line.

    flock() prevents simultaneous FastAPI requests
    from writing over/interleaving with one another.
    """

    CONTACT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    line = (
        json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )

    with CONTACT_FILE.open(
        "a",
        encoding="utf-8",
    ) as f:

        fcntl.flock(
            f.fileno(),
            fcntl.LOCK_EX,
        )

        try:
            f.write(line)
            f.flush()

            os.fsync(
                f.fileno()
            )

        finally:
            fcntl.flock(
                f.fileno(),
                fcntl.LOCK_UN,
            )


def success_response(
    request: Request,
):
    """
    AJAX/fetch submissions receive JSON.

    Ordinary browser form submissions return to
    the contact page.
    """

    accepts = request.headers.get(
        "accept",
        "",
    )

    if "application/json" in accepts:
        return JSONResponse(
            {
                "ok": True,
                "message": (
                    "Thanks. Your message "
                    "has been received."
                ),
            }
        )

    return RedirectResponse(
        url="/contact/?sent=1",
        status_code=303,
    )


# ============================================================================
# Contact endpoint
# ============================================================================

@router.post(
    "/api/contact",
    include_in_schema=False,
)
def submit_contact_form(
    request: Request,

    name: str = Form(...),
    email: str = Form(...),
    message: str = Form(...),

    contact_type: str = Form(
        "general"
    ),

    subscriber: str = Form(
        "no"
    ),

    share_comment: str = Form(
        "no"
    ),

    url: str = Form(
        ""
    ),

    middle_name: str = Form(
        ""
    ),

    form_started_at: str = Form(
        ""
    ),

    form_context: str = Form(
        "",
    ),
):

    # ----------------------------------------------------------------
    # Invisible bot checks
    # ----------------------------------------------------------------

    # Honeypot:
    # return apparent success without storing anything.
    if middle_name.strip():
        return success_response(
            request
        )


    # Only accept our known form version.
    if (
        form_context
        != "wtk-contact-v1"
    ):
        return success_response(
            request
        )


    # Human users normally take at least a few
    # seconds to complete the form.
    try:
        started_ms = int(
            form_started_at
        )

        elapsed_seconds = (
            time.time()
            - (
                started_ms
                / 1000
            )
        )

    except (TypeError, ValueError):
        return success_response(
            request
        )


    # Too fast = likely automated.
    if elapsed_seconds < 5:
        return success_response(
            request
        )


    # A form left open for >24 hours can simply
    # be refreshed and submitted again.
    if elapsed_seconds > 86400:
        return JSONResponse(
            {
                "ok": False,
                "message": (
                    "This form has expired. "
                    "Please refresh the page "
                    "and try again."
                ),
            },
            status_code=400,
        )


    # ----------------------------------------------------------------
    # Normalize values
    # ----------------------------------------------------------------

    name = clean_single_line(
        name,
        max_length=120,
    )

    email = clean_single_line(
        email,
        max_length=254,
    ).lower()

    message = clean_message(
        message
    )

    url = url.strip()


    # ----------------------------------------------------------------
    # Validation
    # ----------------------------------------------------------------

    if not name:
        return JSONResponse(
            {
                "ok": False,
                "message": (
                    "Please enter your name."
                ),
            },
            status_code=400,
        )


    if not valid_email(email):
        return JSONResponse(
            {
                "ok": False,
                "message": (
                    "Please enter a valid "
                    "email address."
                ),
            },
            status_code=400,
        )


    if len(message) < 10:
        return JSONResponse(
            {
                "ok": False,
                "message": (
                    "Please enter a longer "
                    "message."
                ),
            },
            status_code=400,
        )


    if (
        contact_type
        not in ALLOWED_CONTACT_TYPES
    ):
        contact_type = "general"


    if (
        subscriber
        not in ALLOWED_YES_NO
    ):
        subscriber = "no"


    if (
        share_comment
        not in ALLOWED_YES_NO
    ):
        share_comment = "no"


    # Story submissions require a valid URL.
    if contact_type == "story":

        if not valid_http_url(url):
            return JSONResponse(
                {
                    "ok": False,
                    "message": (
                        "Please enter a valid "
                        "news story URL."
                    ),
                },
                status_code=400,
            )

    else:
        # Do not store a stray URL supplied
        # by a modified request.
        url = ""


    # ----------------------------------------------------------------
    # Build record
    # ----------------------------------------------------------------

    record = {
        "id": str(
            uuid4()
        ),

        "received_at": (
            datetime.now(
                timezone.utc
            )
            .isoformat(
                timespec="milliseconds"
            )
            .replace(
                "+00:00",
                "Z",
            )
        ),

        "contact_type":
            contact_type,

        "name":
            name,

        "email":
            email,

        "subscriber":
            subscriber == "yes",

        "share_comment":
            share_comment == "yes",

        "url":
            url or None,

        "message":
            message,
    }


    # ----------------------------------------------------------------
    # Encrypt and Store
    # ----------------------------------------------------------------

    encrypted_record = encrypt_json(
        record,
        purpose=CONTACT_ENCRYPTION_PURPOSE,
    )

    append_jsonl(
        encrypted_record
    )


    return success_response(
        request
    )