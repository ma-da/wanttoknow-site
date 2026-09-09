from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

COOKIE_NAME = "wtk_admin_session"
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 400


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def admin_db_path() -> Path:
    configured = os.environ.get("WTK_ADMIN_DB")
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / "backend/var/admin-dev.sqlite3"


def auth_config_path() -> Path:
    configured = os.environ.get("WTK_ADMIN_AUTH_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    return repo_root() / "backend/var/admin-auth.json"


def cookie_secure() -> bool:
    return os.environ.get("WTK_ADMIN_COOKIE_SECURE", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _connect() -> sqlite3.Connection:
    path = admin_db_path()
    if not path.is_file():
        raise FileNotFoundError(f"Admin SQLite database not found: {path}")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def ensure_auth_schema() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS admin_sessions (
                session_hash TEXT PRIMARY KEY,
                key_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                revoked_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_admin_sessions_key_name
                ON admin_sessions(key_name);

            CREATE INDEX IF NOT EXISTS idx_admin_sessions_revoked_at
                ON admin_sessions(revoked_at);
            """
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(admin_sessions)")}
        if "csrf_token" not in columns:
            conn.execute("ALTER TABLE admin_sessions ADD COLUMN csrf_token TEXT")
        conn.execute(
            "UPDATE admin_sessions SET csrf_token = lower(hex(randomblob(32))) "
            "WHERE csrf_token IS NULL OR csrf_token = ''"
        )


@dataclass(frozen=True)
class AdminIdentity:
    key_name: str
    session_hash: str
    csrf_token: str


def load_access_key_hashes() -> dict[str, str]:
    path = auth_config_path()
    if not path.is_file():
        raise FileNotFoundError(f"Admin auth config not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read admin auth config: {path}") from exc

    keys = data.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("Admin auth config must contain a non-empty 'keys' list")

    result: dict[str, str] = {}
    for item in keys:
        if not isinstance(item, dict):
            raise ValueError("Each admin auth key entry must be an object")
        name = str(item.get("name", "")).strip()
        digest = str(item.get("sha256", "")).strip().lower()
        if not name:
            raise ValueError("Admin auth key entry is missing a name")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError(f"Invalid SHA-256 hash for admin key {name!r}")
        if name in result:
            raise ValueError(f"Duplicate admin key name: {name}")
        result[name] = digest
    return result


def identify_access_key(access_key: str) -> str | None:
    candidate = access_key.strip()
    if not candidate:
        return None

    candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
    for name, stored_hash in load_access_key_hashes().items():
        if hmac.compare_digest(candidate_hash, stored_hash):
            return name
    return None


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(key_name: str) -> str:
    ensure_auth_schema()
    token = secrets.token_urlsafe(48)
    digest = _token_hash(token)
    now = utc_now()
    csrf_token = secrets.token_urlsafe(32)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO admin_sessions(
                session_hash, key_name, created_at, last_seen_at, revoked_at, csrf_token
            ) VALUES (?, ?, ?, ?, NULL, ?)
            """,
            (digest, key_name, now, now, csrf_token),
        )
    return token


def get_identity(request: Request) -> AdminIdentity | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    digest = _token_hash(token)
    try:
        ensure_auth_schema()
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT key_name, session_hash, csrf_token
                FROM admin_sessions
                WHERE session_hash = ? AND revoked_at IS NULL
                """,
                (digest,),
            ).fetchone()
    except (FileNotFoundError, sqlite3.DatabaseError):
        return None

    if row is None:
        return None
    return AdminIdentity(
        key_name=row["key_name"],
        session_hash=row["session_hash"],
        csrf_token=row["csrf_token"],
    )


def revoke_request_session(request: Request) -> None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return
    digest = _token_hash(token)
    try:
        ensure_auth_schema()
        with _connect() as conn:
            conn.execute(
                """
                UPDATE admin_sessions
                SET revoked_at = ?
                WHERE session_hash = ? AND revoked_at IS NULL
                """,
                (utc_now(), digest),
            )
    except (FileNotFoundError, sqlite3.DatabaseError):
        return


def require_admin_api(request: Request) -> AdminIdentity:
    identity = get_identity(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return identity


def require_admin_write(request: Request) -> AdminIdentity:
    identity = require_admin_api(request)
    supplied = request.headers.get("X-CSRF-Token", "")
    if not supplied or not hmac.compare_digest(supplied, identity.csrf_token):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    return identity


def safe_next_path(value: str | None) -> str:
    if not value:
        return "/admin/articles"
    value = value.strip()
    if not value.startswith("/admin") or value.startswith("//"):
        return "/admin/articles"
    return value


def login_redirect(request: Request) -> RedirectResponse:
    path = request.url.path
    if request.url.query:
        path += "?" + request.url.query
    next_value = quote(safe_next_path(path), safe="")
    return RedirectResponse(url=f"/admin/login?next={next_value}", status_code=303)
