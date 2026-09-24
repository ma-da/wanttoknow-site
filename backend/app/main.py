from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi import Request

from .routers import substack_router
from app.routers.contact import router as contact_router
from app import ai_synthesis_router, search_router

from .admin.router import router as admin_articles_router
from .admin.ui_router import router as admin_ui_router
from .admin.auth_router import router as admin_auth_router
from .admin.newsletter_router import router as admin_newsletter_router
from .admin.feedback_router import router as admin_feedback_router
from .admin.analytics_router import router as admin_analytics_router
from app.routers.feedback import router as feedback_router

from app.routers.pageviews import router as pageviews_router

# ============================================================================
# Paths
# ============================================================================

PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parents[2]
)

SITE_ROOT = (
    PROJECT_ROOT
    / "src"
    / "site"
)


# ============================================================================
# FastAPI application
# ============================================================================

app = FastAPI(
    title="WantToKnow.info",
)


# ============================================================================
# API routes
# ============================================================================
app.include_router(
    pageviews_router
)

app.include_router(
    admin_auth_router
)

app.include_router(feedback_router)

app.include_router(
    admin_articles_router
)

app.include_router(
    admin_newsletter_router
)

app.include_router(
    admin_feedback_router
)

app.include_router(
    admin_analytics_router
)

app.include_router(
    admin_ui_router
)

app.include_router(
    admin_ui_router
)

app.include_router(
    admin_articles_router
)

app.include_router(
    substack_router.router,
    prefix="/api",
)

app.include_router(
    contact_router
)

app.include_router(
    search_router.router
)

app.include_router(
    ai_synthesis_router.router
)


@app.get(
    "/api/health",
    tags=["system"],
)
async def health():

    return {
        "status": "ok"
    }

# Middleware for url cleanup

@app.middleware("http")
async def clean_html_urls(
    request: Request,
    call_next,
):
    """
    Local-development equivalent of:

        try_files {path} {path}/ {path}.html

    Example:
        /news/example
        -> internally serves
        /news/example.html

    The browser URL remains extensionless.
    """

    path = request.url.path

    if (
        request.method in {"GET", "HEAD"}
        and path != "/"
        and not path.startswith(
            (
                "/api/",
                "/admin/",
            )
        )
    ):
        relative_path = path.lstrip("/")

        requested_file = (
            SITE_ROOT
            / relative_path
        )

        html_file = Path(
            str(requested_file)
            + ".html"
        )

        # Preserve real files/directories first.
        if (
            not requested_file.exists()
            and html_file.is_file()
        ):
            request.scope["path"] = (
                path + ".html"
            )

    return await call_next(request)

# ============================================================================
# Static website
#
# Keep this LAST.
# ============================================================================

# ============================================================================
# Admin static assets
# ============================================================================

app.mount(
    "/admin/assets",
    StaticFiles(
        directory=(
            Path(__file__).resolve().parent
            / "admin"
            / "static"
        ),
    ),
    name="admin-assets",
)


app.mount(
    "/",
    StaticFiles(
        directory=SITE_ROOT,
        html=True,
    ),
    name="site",
)
