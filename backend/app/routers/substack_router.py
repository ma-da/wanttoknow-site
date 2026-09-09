from fastapi import (
    APIRouter,
    HTTPException,
    Response,
)

from ..services.substack import (
    get_substack_feed,
)


router = APIRouter(
    prefix="/substack",
    tags=["substack"],
)


@router.get("")
async def substack_feed():

    try:

        feed = await get_substack_feed()


    except Exception as exc:

        print(
            "\nSUBSTACK FETCH ERROR:",
            repr(exc),
            "\n"
        )

        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to retrieve "
                "the Substack feed."
            ),
        ) from exc


    return Response(
        content=feed,
        media_type="application/rss+xml",
        headers={
            "Cache-Control":
                "public, max-age=300"
        },
    )