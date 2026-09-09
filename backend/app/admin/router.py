from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .auth import AdminIdentity, require_admin_api, require_admin_write
from .article_edit import connect_writable, create_draft_article, delete_new_draft_article, reference_data, update_article
from .article_workflow import current_batch_info
from .article_publish import PublishError, publish_article, publish_current_batch
from .article_withdrawal import cancel_withdrawal, request_withdrawal
from .image_processing import MAX_UPLOAD_BYTES, ImageProcessingError, process_image_upload
from .image_staging import (
    discard_staged_image,
    stage_processed_image,
    staged_image_file,
    staged_image_status,
)
from .article_query import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    SORTS,
    connect_readonly,
    get_article,
    list_articles,
)

router = APIRouter(
    prefix="/api/admin/articles",
    tags=["admin-articles"],
    dependencies=[Depends(require_admin_api)],
)




class ArticleDraftCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_url: str = Field(min_length=1, max_length=4000)




class ArticleWithdrawalRequest(BaseModel):
    reason_code: str = Field(min_length=1, max_length=50)
    reason_text: str = Field(default="", max_length=2000)
    redirect_path: str = Field(default="", max_length=2000)


class ArticleUpdateRequest(BaseModel):
    title: str = Field(max_length=500)
    slug: str = Field(max_length=500)
    legacy_url: str = Field(default="", max_length=2000)
    publication_date: str = Field(max_length=20)
    posted_date: str = Field(max_length=20)
    publication_group: str = Field(max_length=250)
    publication_detail: str = Field(default="", max_length=1000)
    publication_raw: str = Field(default="", max_length=1000)
    source_url: str = Field(default="", max_length=4000)
    summary_markdown: str = Field(default="", max_length=100000)
    note_markdown: str = Field(default="", max_length=50000)
    tags: list[str] = Field(default_factory=list, max_length=200)
    priority: int
    image_caption_markdown: str = Field(default="", max_length=10000)
    image_caption_text: str = Field(default="", max_length=10000)


@router.get("")
def articles_list(
    q: str | None = Query(default=None, max_length=250),
    category: str | None = Query(default=None, max_length=100),
    publisher: str | None = Query(default=None, max_length=250),
    edit_state: str | None = Query(default=None),
    workflow_state: str | None = Query(default=None),
    sort: str = Query(default="posted_desc"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = Query(default=None, max_length=1000),
):
    if sort not in SORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sort. Choose one of: {', '.join(SORTS)}",
        )

    try:
        with connect_readonly() as conn:
            return list_articles(
                conn,
                q=q,
                category=category,
                publisher=publisher,
                edit_state=edit_state,
                workflow_state=workflow_state,
                sort=sort,
                limit=limit,
                cursor=cursor,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ValueError, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/drafts", status_code=201)
def article_draft_create(
    payload: ArticleDraftCreateRequest,
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return create_draft_article(
                conn,
                title=payload.title,
                source_url=payload.source_url,
                created_by=identity.key_name,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Unable to reserve a unique article ID or slug") from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Unable to create article draft") from exc


@router.get("/batch/current")
def article_current_batch():
    try:
        with connect_writable() as conn:
            batch = current_batch_info(conn, create=False)
            if batch is None:
                return {
                    "batch": None,
                    "publishing_enabled": False,
                    "publishing_message": "No draft batch is open.",
                }
            return {
                "batch": batch,
                "publishing_enabled": bool(batch.get("total")),
                "publishing_message": "Publish the complete current draft batch.",
            }
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Unable to read current article batch") from exc


@router.post("/batch/current/publish")
def article_batch_publish(
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return publish_current_batch(conn, actor=identity.key_name)
    except PublishError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=500, detail=f"Batch publication failed: {exc}") from exc


@router.post("/{article_id}/publish")
def article_publish_one(
    article_id: int,
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return publish_article(conn, article_id, actor=identity.key_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PublishError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=500, detail=f"Article publication failed: {exc}") from exc


@router.get("/reference-data")
def article_reference_data():
    try:
        return reference_data()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/{article_id}")
def article_draft_delete(
    article_id: int,
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return delete_new_draft_article(conn, article_id, deleted_by=identity.key_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (OSError, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=500, detail="Unable to delete article draft") from exc




@router.post("/{article_id}/withdrawal", status_code=201)
def article_withdrawal_request(
    article_id: int,
    payload: ArticleWithdrawalRequest,
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return request_withdrawal(
                conn,
                article_id,
                reason_code=payload.reason_code,
                reason_text=payload.reason_text,
                redirect_path=payload.redirect_path,
                requested_by=identity.key_name,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Unable to schedule article removal") from exc


@router.delete("/{article_id}/withdrawal")
def article_withdrawal_cancel(
    article_id: int,
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return cancel_withdrawal(conn, article_id, cancelled_by=identity.key_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Unable to cancel article removal") from exc


@router.get("/{article_id}")
def article_detail(article_id: int):
    try:
        with connect_readonly() as conn:
            article = get_article(conn, article_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Admin article database error") from exc

    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article


@router.put("/{article_id}")
def article_update(
    article_id: int,
    payload: ArticleUpdateRequest,
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return update_article(
                conn,
                article_id,
                payload.model_dump(),
                saved_by=identity.key_name,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Unable to save article draft") from exc


async def _read_raw_image_body(request: Request) -> bytes:
    content_encoding = request.headers.get("content-encoding", "").strip().lower()
    if content_encoding not in {"", "identity"}:
        raise HTTPException(status_code=415, detail="Compressed request bodies are not supported")

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            announced = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
        if announced > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image exceeds the 5 MB upload limit")

    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type and media_type not in {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/octet-stream",
    }:
        raise HTTPException(status_code=415, detail="Use a JPEG, PNG or WebP image")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Image exceeds the 5 MB upload limit")
        chunks.append(bytes(chunk))

    if total == 0:
        raise HTTPException(status_code=400, detail="Image upload is empty")
    return b"".join(chunks)


@router.get("/{article_id}/image")
def article_image_status(article_id: int):
    try:
        with connect_writable() as conn:
            return staged_image_status(conn, article_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Unable to read image staging state") from exc


@router.post("/{article_id}/image", status_code=201)
async def article_image_upload(
    article_id: int,
    request: Request,
    identity: AdminIdentity = Depends(require_admin_write),
):
    raw = await _read_raw_image_body(request)
    try:
        processed = process_image_upload(raw)
    except ImageProcessingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        # Do not retain the original upload beyond this request.
        raw = b""

    try:
        with connect_writable() as conn:
            return stage_processed_image(
                conn,
                article_id,
                processed,
                staged_by=identity.key_name,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=500, detail="Unable to stage processed image") from exc


@router.get("/{article_id}/image/{variant}")
def article_image_preview(article_id: int, variant: str):
    if variant not in {"full", "thumb"}:
        raise HTTPException(status_code=404, detail="Unknown image preview variant")
    try:
        with connect_writable() as conn:
            path = staged_image_file(conn, article_id, variant)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except sqlite3.DatabaseError as exc:
        raise HTTPException(status_code=500, detail="Unable to read staged image") from exc

    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/{article_id}/image")
def article_image_discard(
    article_id: int,
    identity: AdminIdentity = Depends(require_admin_write),
):
    try:
        with connect_writable() as conn:
            return discard_staged_image(conn, article_id, discarded_by=identity.key_name)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, sqlite3.DatabaseError) as exc:
        raise HTTPException(status_code=500, detail="Unable to discard staged image") from exc
