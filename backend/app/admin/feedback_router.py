from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Path as ApiPath,
    Query,
    Request,
)
from fastapi.responses import FileResponse
from pydantic import (
    BaseModel,
    Field,
)

from .auth import (
    AdminIdentity,
    get_identity,
    login_redirect,
    require_admin_api,
    require_admin_write,
)
from .feedback_store import (
    load_contacts,
    load_surveys,
    update_feedback_admin_state,
)


router = APIRouter(
    tags=["admin-feedback"],
)

TEMPLATE = (
    Path(__file__).resolve().parent
    / "templates"
    / "feedback.html"
)


class FeedbackAdminPatch(
    BaseModel,
):
    is_read: bool | None = None
    is_archived: bool | None = None

    internal_note: str | None = Field(
        default=None,
        max_length=5000,
    )


def _identity_label(
    identity: AdminIdentity,
) -> str:
    for attribute in (
        "name",
        "username",
        "label",
        "access_key_name",
        "key_name",
    ):
        value = getattr(
            identity,
            attribute,
            None,
        )

        if value:
            return str(value)

    return "admin"


# ============================================================================
# Admin UI
# ============================================================================

@router.get(
    "/admin/feedback",
    include_in_schema=False,
)
def feedback_page(
    request: Request,
):
    identity = get_identity(
        request
    )

    if identity is None:
        return login_redirect(
            request
        )

    if not TEMPLATE.is_file():
        raise HTTPException(
            status_code=500,
            detail="Feedback template missing.",
        )

    return FileResponse(
        TEMPLATE,
        media_type="text/html",
        headers={
            "Cache-Control": "no-store",
        },
    )


# ============================================================================
# Contact submissions
# ============================================================================

@router.get(
    "/api/admin/feedback/contact",
)
def contact_feedback(
    identity: AdminIdentity = Depends(
        require_admin_api
    ),
    limit: int = Query(
        default=250,
        ge=1,
        le=1000,
    ),
):
    try:
        return load_contacts(
            limit=limit
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Contact submissions unavailable."
            ),
        ) from exc


# ============================================================================
# Survey responses
# ============================================================================

@router.get(
    "/api/admin/feedback/survey",
)
def survey_feedback(
    identity: AdminIdentity = Depends(
        require_admin_api
    ),
    limit: int = Query(
        default=250,
        ge=1,
        le=1000,
    ),
):
    try:
        return load_surveys(
            limit=limit
        )

    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Survey responses unavailable."
            ),
        ) from exc


# ============================================================================
# Admin triage state
# ============================================================================

@router.patch(
    "/api/admin/feedback/{source}/{record_key}",
)
def update_feedback_state(
    payload: FeedbackAdminPatch,

    identity: AdminIdentity = Depends(
        require_admin_write
    ),

    source: str = ApiPath(
        pattern="^(contact|survey)$",
    ),

    record_key: int = ApiPath(
        ge=1,
    ),
):
    if (
        payload.is_read is None
        and payload.is_archived is None
        and payload.internal_note is None
    ):
        raise HTTPException(
            status_code=400,
            detail="No feedback fields supplied.",
        )

    try:
        admin_state = (
            update_feedback_admin_state(
                source,
                str(record_key),
                is_read=payload.is_read,
                is_archived=payload.is_archived,
                internal_note=payload.internal_note,
                updated_by=_identity_label(
                    identity
                ),
            )
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "source": source,
        "record_key": str(
            record_key
        ),
        "admin": admin_state,
    }
