from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from .auth import AdminIdentity, require_admin_api, require_admin_write
from .newsletter_render import render_newsletter, newsletter_article_choices
from .newsletter_store import (
    delete_newsletter,
    list_newsletters,
    load_newsletter,
    save_newsletter,
    validate_issue_date,
)


ADMIN_DIR = Path(__file__).resolve().parent
BUILDER_HTML = ADMIN_DIR / "templates" / "newsletters.html"

router = APIRouter(tags=["admin-newsletters"])


class NewsletterDraftRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    headlines: list[str] = Field(default_factory=list)
    regular_preview_items: list[str] = Field(default_factory=list)
    inspiring_preview_items: list[str] = Field(default_factory=list)
    special_note_markdown: str = Field(default="", max_length=50000)
    regular_article_ids: list[str] = Field(default_factory=list)
    inspiring_article_ids: list[str] = Field(default_factory=list)


def _payload_dict(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


def _clean_date(issue_date: str) -> str:
    try:
        return validate_issue_date(issue_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------
# Builder page
# ---------------------------------------------------------------------

@router.get("/admin/newsletters")
def newsletter_builder(
    identity: AdminIdentity = Depends(require_admin_api),
):
    if not BUILDER_HTML.exists():
        raise HTTPException(
            status_code=503,
            detail="Newsletter builder template is not installed",
        )

    return FileResponse(BUILDER_HTML)


# ---------------------------------------------------------------------
# Draft API
# ---------------------------------------------------------------------

@router.get("/api/admin/newsletters")
def newsletter_list(
    identity: AdminIdentity = Depends(require_admin_api),
):
    return {
        "newsletters": list_newsletters(),
    }


@router.get("/api/admin/newsletters/article-picker")
def newsletter_article_picker(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=30, ge=1, le=100),
    identity: AdminIdentity = Depends(require_admin_api),
):
    return {
        "articles": newsletter_article_choices(
            q,
            limit=limit,
        )
    }


@router.get("/api/admin/newsletters/{issue_date}")
def newsletter_get(
    issue_date: str,
    identity: AdminIdentity = Depends(require_admin_api),
):
    issue_date = _clean_date(issue_date)

    try:
        return {
            "newsletter": load_newsletter(issue_date),
        }
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.put("/api/admin/newsletters/{issue_date}")
def newsletter_save(
    issue_date: str,
    payload: NewsletterDraftRequest,
    identity: AdminIdentity = Depends(require_admin_write),
):
    issue_date = _clean_date(issue_date)

    try:
        newsletter = save_newsletter(
            issue_date,
            _payload_dict(payload),
        )

        return {
            "newsletter": newsletter,
        }

    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to save newsletter draft",
        ) from exc


@router.delete("/api/admin/newsletters/{issue_date}")
def newsletter_delete(
    issue_date: str,
    identity: AdminIdentity = Depends(require_admin_write),
):
    issue_date = _clean_date(issue_date)

    try:
        deleted = delete_newsletter(issue_date)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to delete newsletter draft",
        ) from exc

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Newsletter draft not found",
        )

    return {
        "deleted": True,
        "newsletter_id": issue_date,
    }


# ---------------------------------------------------------------------
# Rendered output
# ---------------------------------------------------------------------

@router.get("/admin/newsletters/{issue_date}/preview")
def newsletter_preview(
    issue_date: str,
    identity: AdminIdentity = Depends(require_admin_api),
):
    issue_date = _clean_date(issue_date)

    try:
        newsletter = load_newsletter(issue_date)
        html = render_newsletter(newsletter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to render newsletter",
        ) from exc

    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/admin/newsletters/{issue_date}/download")
def newsletter_download(
    issue_date: str,
    identity: AdminIdentity = Depends(require_admin_api),
):
    issue_date = _clean_date(issue_date)

    try:
        newsletter = load_newsletter(issue_date)
        html = render_newsletter(newsletter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to render newsletter",
        ) from exc

    filename = f"wanttoknow-newsletter-{issue_date}.html"

    return Response(
        content=html.encode("utf-8"),
        media_type="text/html",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
