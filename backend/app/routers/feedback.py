"""
Anonymous WantToKnow.info website feedback endpoint.

- Accepts 1-5 ratings plus three optional open-ended responses.
- Appends one JSON object per line to a JSONL file.
- Does not write IP addresses, email addresses, user agents, or other
  identifying information to the response file.
- Uses an in-memory salted hash of the client IP solely for a 30-second
  rate limit. The raw IP is not retained by this module.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints


router = APIRouter(tags=["feedback"])

FEEDBACK_FILE = Path(
    os.getenv(
        "WTK_FEEDBACK_FILE",
        "/var/lib/wanttoknow/feedback/site-feedback.jsonl",
    )
)

RATE_LIMIT_SECONDS = 30
MAX_REQUEST_BYTES = 16_384

# Set WTK_TRUST_PROXY_IP_HEADERS=1 only when the app is actually behind a
# trusted reverse proxy / Cloudflare path that replaces these headers.
TRUST_PROXY_IP_HEADERS = (
    os.getenv("WTK_TRUST_PROXY_IP_HEADERS", "0").strip() == "1"
)

# A new random salt is created each time the process starts. This lets us use
# an IP-derived key for short-lived rate limiting without retaining the IP.
_RATE_SALT = secrets.token_bytes(32)
_RATE_LOCK = threading.Lock()
_LAST_SUBMISSION_BY_CLIENT: dict[str, float] = {}

_FILE_LOCK = threading.Lock()

ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=3000),
]


class Ratings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reliable: int = Field(ge=1, le=5)
    authoritative: int = Field(ge=1, le=5)
    easy_to_navigate: int = Field(ge=1, le=5)
    nonpartisan: int = Field(ge=1, le=5)
    easy_to_understand: int = Field(ge=1, le=5)
    visually_appealing: int = Field(ge=1, le=5)
    interesting: int = Field(ge=1, le=5)
    overall: int = Field(ge=1, le=5)


class FeedbackSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ratings: Ratings
    love: ShortText = ""
    hate: ShortText = ""
    missing: ShortText = ""

    # Honeypot. Real users never see or fill this.
    website: Annotated[
        str,
        StringConstraints(strip_whitespace=True, max_length=200),
    ] = ""


def _get_client_ip(request: Request) -> str:
    """
    Return the address used only for rate limiting.

    By default this is request.client.host.

    If WTK_TRUST_PROXY_IP_HEADERS=1, prefer Cloudflare's CF-Connecting-IP,
    then the first X-Forwarded-For value. Only enable that setting when your
    proxy/origin configuration prevents clients from supplying forged values.
    """
    if TRUST_PROXY_IP_HEADERS:
        cloudflare_ip = request.headers.get("cf-connecting-ip")
        if cloudflare_ip:
            return cloudflare_ip.strip()

        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def _rate_key(request: Request) -> str:
    client_ip = _get_client_ip(request)
    return hashlib.blake2b(
        client_ip.encode("utf-8"),
        key=_RATE_SALT,
        digest_size=16,
    ).hexdigest()


def _enforce_rate_limit(request: Request) -> int | None:
    """
    Return None when allowed, otherwise the number of seconds to retry after.

    The map is opportunistically cleaned so it never grows indefinitely.
    """
    now = time.monotonic()
    key = _rate_key(request)

    with _RATE_LOCK:
        last = _LAST_SUBMISSION_BY_CLIENT.get(key)

        if last is not None:
            elapsed = now - last
            if elapsed < RATE_LIMIT_SECONDS:
                return max(1, math.ceil(RATE_LIMIT_SECONDS - elapsed))

        # Record the attempt now, rather than after the disk write, to prevent
        # rapid concurrent submissions from the same client.
        _LAST_SUBMISSION_BY_CLIENT[key] = now

        # Opportunistic cleanup of expired keys.
        cutoff = now - (RATE_LIMIT_SECONDS * 2)
        expired = [
            client_key
            for client_key, last_seen in _LAST_SUBMISSION_BY_CLIENT.items()
            if last_seen < cutoff
        ]
        for client_key in expired:
            _LAST_SUBMISSION_BY_CLIENT.pop(client_key, None)

    return None


def _append_jsonl(record: dict) -> None:
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)

    line = (
        json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    # Thread lock protects concurrent calls inside one worker.
    # flock protects against multiple local worker processes writing at once.
    with _FILE_LOCK:
        fd = os.open(
            FEEDBACK_FILE,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            with os.fdopen(fd, "ab", closefd=False) as file_obj:
                fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
                file_obj.write(line)
                file_obj.flush()
                os.fsync(file_obj.fileno())
                fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
        finally:
            os.close(fd)


@router.post("/api/feedback", status_code=status.HTTP_201_CREATED)
def submit_feedback(
    payload: FeedbackSubmission,
    request: Request,
    response: Response,
) -> dict[str, bool]:
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type.lower():
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type must be application/json.",
        )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Feedback submission is too large.",
                )
        except ValueError:
            pass

    # Honeypot: silently accept obvious bot submissions without storing them.
    if payload.website:
        return {"ok": True}

    retry_after = _enforce_rate_limit(request)
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Please wait before submitting another response.",
            headers={"Retry-After": str(retry_after)},
        )

    record = {
        "submitted_at": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "ratings": payload.ratings.model_dump(),
        "love": payload.love,
        "hate": payload.hate,
        "missing": payload.missing,
    }

    try:
        _append_jsonl(record)
    except OSError:
        # Don't leak filesystem paths or server details to the browser.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The feedback could not be saved.",
        )

    return {"ok": True}
