from __future__ import annotations

import asyncio
import time

from urllib.error import (
    HTTPError,
    URLError,
)

from urllib.request import (
    Request,
    urlopen,
)


SUBSTACK_FEED_URL = (
    "https://wtkconsciousmedia.substack.com/feed"
)

CACHE_SECONDS = 600

REQUEST_TIMEOUT = 15


_cache_body: str | None = None
_cache_expires_at: float = 0.0

_cache_lock = asyncio.Lock()


# ============================================================================
# Synchronous RSS fetch
# ============================================================================

def _fetch_substack_feed() -> str:
    """
    Fetch the public Substack RSS feed.

    This function is synchronous. The public async function below runs it
    in a worker thread so it does not block FastAPI's event loop.
    """

    request = Request(
        SUBSTACK_FEED_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),

            "Accept": (
                "application/rss+xml,"
                "application/xml,"
                "text/xml;q=0.9,"
                "*/*;q=0.8"
            ),

            "Accept-Language":
                "en-US,en;q=0.9",
        },
    )


    try:

        with urlopen(
            request,
            timeout=REQUEST_TIMEOUT,
        ) as response:

            body = response.read().decode(
                "utf-8",
                errors="replace",
            )


    except HTTPError as exc:

        raise RuntimeError(
            "Substack returned "
            f"HTTP {exc.code}."
        ) from exc


    except URLError as exc:

        raise RuntimeError(
            "Unable to connect "
            "to the Substack feed."
        ) from exc


    if not body.strip():

        raise RuntimeError(
            "Substack returned "
            "an empty RSS feed."
        )


    return body


# ============================================================================
# Cached asynchronous interface
# ============================================================================

async def get_substack_feed() -> str:
    """
    Return cached Substack RSS.

    The remote feed is refreshed at most once per CACHE_SECONDS.
    """

    global _cache_body
    global _cache_expires_at


    now = time.monotonic()


    if (
        _cache_body is not None
        and now < _cache_expires_at
    ):
        return _cache_body


    async with _cache_lock:

        now = time.monotonic()


        # Another request may have refreshed
        # the feed while this request waited.

        if (
            _cache_body is not None
            and now < _cache_expires_at
        ):
            return _cache_body


        body = await asyncio.to_thread(
            _fetch_substack_feed
        )


        _cache_body = body

        _cache_expires_at = (
            time.monotonic()
            + CACHE_SECONDS
        )


        return body