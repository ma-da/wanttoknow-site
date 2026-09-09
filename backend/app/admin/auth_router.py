from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .auth import (
    COOKIE_MAX_AGE_SECONDS,
    COOKIE_NAME,
    cookie_secure,
    create_session,
    get_identity,
    identify_access_key,
    revoke_request_session,
    safe_next_path,
)

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

router = APIRouter(tags=["admin-auth"])


class LoginRequest(BaseModel):
    access_key: str = Field(min_length=20, max_length=4096)
    next: str | None = Field(default=None, max_length=2000)


def _no_store_file(path: Path, media_type: str) -> FileResponse:
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/admin/login", include_in_schema=False)
def login_page(request: Request):
    if get_identity(request) is not None:
        return RedirectResponse(
            url=safe_next_path(request.query_params.get("next")),
            status_code=303,
        )
    return _no_store_file(TEMPLATES_DIR / "login.html", "text/html")


@router.get("/admin/assets/login.js", include_in_schema=False)
def login_js() -> FileResponse:
    return _no_store_file(STATIC_DIR / "login.js", "text/javascript")


@router.post("/api/admin/login")
def login(payload: LoginRequest):
    try:
        key_name = identify_access_key(payload.access_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if key_name is None:
        raise HTTPException(status_code=401, detail="Invalid access key")

    token = create_session(key_name)
    response = JSONResponse(
        {
            "ok": True,
            "name": key_name,
            "redirect": safe_next_path(payload.next),
        }
    )
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


@router.get("/api/admin/session")
def session_status(request: Request):
    identity = get_identity(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    return {"authenticated": True, "name": identity.key_name, "csrf_token": identity.csrf_token}


@router.post("/admin/logout", include_in_schema=False)
def logout(request: Request):
    revoke_request_session(request)
    response = RedirectResponse(url="/admin/login", status_code=303)
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=cookie_secure(),
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return response
