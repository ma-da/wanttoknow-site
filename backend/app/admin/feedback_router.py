from __future__ import annotations

from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
)
from fastapi.responses import FileResponse

from .auth import (
    AdminIdentity,
    get_identity,
    login_redirect,
    require_admin_api,
)
from .feedback_store import (
    load_contacts,
    load_surveys,
)


router = APIRouter(
    tags=["admin-feedback"],
)

TEMPLATE = (
    Path(__file__).resolve().parent
    / "templates"
    / "feedback.html"
)


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
