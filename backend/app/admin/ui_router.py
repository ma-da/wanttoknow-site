from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse

from .auth import get_identity, login_redirect

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

router = APIRouter(tags=["admin-ui"])


def _no_store_file(path: Path, media_type: str) -> FileResponse:
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/admin", include_in_schema=False)
def admin_home(request: Request):
    if get_identity(request) is None:
        return login_redirect(request)
    return RedirectResponse(url="/admin/articles", status_code=303)


@router.get("/admin/articles", include_in_schema=False)
def articles_page(request: Request):
    if get_identity(request) is None:
        return login_redirect(request)
    return _no_store_file(TEMPLATES_DIR / "articles.html", "text/html")


@router.get("/admin/articles/{article_id}/edit", include_in_schema=False)
def article_edit_page(request: Request, article_id: int):
    if get_identity(request) is None:
        return login_redirect(request)
    return _no_store_file(TEMPLATES_DIR / "article-edit.html", "text/html")


@router.get("/admin/assets/admin.css", include_in_schema=False)
def admin_css() -> FileResponse:
    return _no_store_file(STATIC_DIR / "admin.css", "text/css")


@router.get("/admin/assets/articles.js", include_in_schema=False)
def articles_js() -> FileResponse:
    return _no_store_file(STATIC_DIR / "articles.js", "text/javascript")


@router.get("/admin/assets/article-edit.js", include_in_schema=False)
def article_edit_js() -> FileResponse:
    return _no_store_file(STATIC_DIR / "article-edit.js", "text/javascript")
