from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from .auth import AdminIdentity, require_admin_api, require_admin_write
from .article_edit import connect_writable
from .article_publish import PublishError, publish_selected_batch
from .newsletter_editor import (
    NewsletterEditorConflict,
    NewsletterEditorError,
    apply_article_content_changes,
    article_tokens,
    load_article_states,
    parse_editor_document,
    publishable_editor_articles,
    render_editor_document,
)
from .newsletter_render import (
    newsletter_article_choices,
    newsletter_template_choices,
    render_newsletter,
)
from .newsletter_store import (
    NewsletterConflictError,
    delete_newsletter,
    list_newsletters,
    load_newsletter,
    save_newsletter,
    validate_issue_date,
)


ADMIN_DIR = Path(__file__).resolve().parent
BUILDER_HTML = ADMIN_DIR / "templates" / "newsletters.html"
EDITOR_HTML = ADMIN_DIR / "templates" / "newsletter-editor.html"

router = APIRouter(tags=["admin-newsletters"])


class NewsletterDraftRequest(BaseModel):
    title: str = Field(default="", max_length=500)
    headlines: list[str] = Field(default_factory=list)
    regular_preview_items: list[str] = Field(default_factory=list)
    inspiring_preview_items: list[str] = Field(default_factory=list)
    special_note_markdown: str = Field(default="", max_length=50000)
    regular_article_ids: list[str] = Field(default_factory=list)
    inspiring_article_ids: list[str] = Field(default_factory=list)


class NewsletterEditorPreviewRequest(BaseModel):
    document: str = Field(max_length=500000)
    template_key: str = Field(default="standard", max_length=80)


class NewsletterEditorSaveRequest(NewsletterEditorPreviewRequest):
    newsletter_updated_at: str = Field(max_length=100)
    article_tokens: dict[str, str] = Field(default_factory=dict)
    publish_articles: bool = False


def _payload_dict(payload: BaseModel) -> dict[str, Any]:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    return payload.dict()


def _clean_date(issue_date: str) -> str:
    try:
        return validate_issue_date(issue_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _selected_article_ids(newsletter: dict[str, Any]) -> list[str]:
    return [
        *[
            str(value)
            for value in newsletter.get("regular_article_ids", [])
        ],
        *[
            str(value)
            for value in newsletter.get("inspiring_article_ids", [])
        ],
    ]


def _validate_template_key(template_key: str) -> str:
    key = str(template_key or "standard").strip() or "standard"
    valid = {
        item["key"]
        for item in newsletter_template_choices()
    }
    if key not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown newsletter template: {key}",
        )
    return key


def _editor_payload(
    newsletter: dict[str, Any],
    article_states: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "newsletter": newsletter,
        "document": render_editor_document(
            newsletter,
            article_states,
        ),
        "article_tokens": article_tokens(article_states),
        "templates": newsletter_template_choices(),
    }


# ---------------------------------------------------------------------
# Builder/editor pages
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


@router.get("/admin/newsletters/{issue_date}/editor")
def newsletter_editor_page(
    issue_date: str,
    identity: AdminIdentity = Depends(require_admin_api),
):
    _clean_date(issue_date)

    if not EDITOR_HTML.exists():
        raise HTTPException(
            status_code=503,
            detail="Newsletter editor template is not installed",
        )

    return FileResponse(
        EDITOR_HTML,
        headers={"Cache-Control": "no-store"},
    )


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
# Markdown newsletter editor API
# ---------------------------------------------------------------------

@router.get("/api/admin/newsletters/{issue_date}/editor")
def newsletter_editor_get(
    issue_date: str,
    identity: AdminIdentity = Depends(require_admin_api),
):
    issue_date = _clean_date(issue_date)

    try:
        newsletter = load_newsletter(issue_date)
        article_ids = _selected_article_ids(newsletter)

        with connect_writable() as conn:
            states = load_article_states(conn, article_ids)

        return _editor_payload(newsletter, states)

    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/admin/newsletters/{issue_date}/editor/preview")
def newsletter_editor_preview(
    issue_date: str,
    payload: NewsletterEditorPreviewRequest,
    identity: AdminIdentity = Depends(require_admin_api),
):
    issue_date = _clean_date(issue_date)
    template_key = _validate_template_key(payload.template_key)

    try:
        newsletter = load_newsletter(issue_date)
        article_ids = _selected_article_ids(newsletter)

        with connect_writable() as conn:
            states = load_article_states(conn, article_ids)

        parsed = parse_editor_document(
            payload.document,
            newsletter=newsletter,
            article_states=states,
        )

        preview_newsletter = {
            **newsletter,
            "template_key": template_key,
            "title": parsed["title"],
            "headlines": parsed["headlines"],
            "regular_preview_items": parsed[
                "regular_preview_items"
            ],
            "inspiring_preview_items": parsed[
                "inspiring_preview_items"
            ],
            "special_note_markdown": parsed[
                "special_note_markdown"
            ],
            "regular_article_ids": parsed[
                "regular_article_ids"
            ],
            "inspiring_article_ids": parsed[
                "inspiring_article_ids"
            ],
        }

        article_content = parsed["article_content"]
        html = render_newsletter(
            preview_newsletter,
            summary_overrides={
                article_id: content["summary_markdown"]
                for article_id, content in article_content.items()
            },
            note_overrides={
                article_id: content["note_markdown"]
                for article_id, content in article_content.items()
            },
        )

        return HTMLResponse(
            content=html,
            headers={"Cache-Control": "no-store"},
        )

    except NewsletterEditorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/api/admin/newsletters/{issue_date}/editor")
def newsletter_editor_save(
    issue_date: str,
    payload: NewsletterEditorSaveRequest,
    identity: AdminIdentity = Depends(require_admin_write),
):
    issue_date = _clean_date(issue_date)
    template_key = _validate_template_key(payload.template_key)

    try:
        newsletter = load_newsletter(issue_date)

        if (
            str(newsletter.get("updated_at", ""))
            != str(payload.newsletter_updated_at)
        ):
            raise NewsletterConflictError(
                "This newsletter changed after the editor was opened. "
                "Reload before saving so newer changes are not overwritten."
            )

        article_ids = _selected_article_ids(newsletter)

        with connect_writable() as conn:
            states = load_article_states(conn, article_ids)

            parsed = parse_editor_document(
                payload.document,
                newsletter=newsletter,
                article_states=states,
            )

            receipts, changed_ids, states = (
                apply_article_content_changes(
                    conn,
                    article_content=parsed["article_content"],
                    expected_tokens={
                        str(key): str(value)
                        for key, value in payload.article_tokens.items()
                    },
                    receipts=dict(
                        newsletter.get(
                            "editor_article_changes",
                            {},
                        )
                    ),
                    actor=identity.key_name,
                )
            )

            save_payload = {
                **newsletter,
                "template_key": template_key,
                "title": parsed["title"],
                "headlines": parsed["headlines"],
                "regular_preview_items": parsed[
                    "regular_preview_items"
                ],
                "inspiring_preview_items": parsed[
                    "inspiring_preview_items"
                ],
                "special_note_markdown": parsed[
                    "special_note_markdown"
                ],
                "regular_article_ids": parsed[
                    "regular_article_ids"
                ],
                "inspiring_article_ids": parsed[
                    "inspiring_article_ids"
                ],
                "editor_article_changes": receipts,
            }

            saved = save_newsletter(
                issue_date,
                save_payload,
                expected_updated_at=payload.newsletter_updated_at,
            )

            published_ids: list[int] = []
            publication_result: dict[str, Any] | None = None
            publication_error = ""

            if payload.publish_articles:
                try:
                    states = load_article_states(
                        conn,
                        _selected_article_ids(saved),
                    )
                    publish_ids = publishable_editor_articles(
                        conn,
                        article_states=states,
                        receipts=receipts,
                    )

                    if publish_ids:
                        publication_result = publish_selected_batch(
                            conn,
                            publish_ids,
                            actor=identity.key_name,
                        )
                        published_ids = publish_ids

                        receipts = {
                            article_id: receipt
                            for article_id, receipt in receipts.items()
                            if int(article_id) not in set(published_ids)
                        }

                        saved = save_newsletter(
                            issue_date,
                            {
                                **saved,
                                "editor_article_changes": receipts,
                            },
                            expected_updated_at=saved["updated_at"],
                        )

                except (NewsletterEditorError, PublishError) as exc:
                    # Article/newsletter edits are already safely saved as
                    # drafts. Return the new revision tokens rather than
                    # turning this into a stale-client 409.
                    publication_error = str(exc)

            states = load_article_states(
                conn,
                _selected_article_ids(saved),
            )

        response = _editor_payload(saved, states)
        response.update(
            {
                "changed_article_ids": changed_ids,
                "published_article_ids": [
                    str(value)
                    for value in published_ids
                ],
                "publication_result": publication_result,
                "publication_error": publication_error,
            }
        )
        return response

    except NewsletterConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NewsletterEditorConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NewsletterEditorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to save newsletter/article edits",
        ) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail="Unable to save newsletter editor changes",
        ) from exc


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
