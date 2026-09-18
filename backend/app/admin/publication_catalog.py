from __future__ import annotations

import fcntl
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]

PUBLICATION_PATH = (
    REPO_ROOT
    / "src"
    / "site"
    / "data"
    / "publication-canonicalization.json"
)

LOCK_PATH = (
    REPO_ROOT
    / "backend"
    / "var"
    / "publication-canonicalization.lock"
)


def _slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "publication"


def _clean_name(value: str) -> str:
    return " ".join(str(value or "").split())


def _write_atomic(
    path: Path,
    data: dict[str, Any],
) -> None:
    """
    Write JSON atomically while preserving this project's CRLF
    line-ending convention and existing object insertion order.
    """

    temp_path = path.with_name(
        f"{path.name}.tmp.{os.getpid()}"
    )

    original_mode = path.stat().st_mode & 0o777

    text = (
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )

    # json.dumps creates LF internally. Convert explicitly to
    # CRLF bytes so Python newline translation cannot alter it.
    payload = text.replace(
        "\n",
        "\r\n",
    ).encode("utf-8")

    try:
        with temp_path.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(
            temp_path,
            original_mode,
        )

        os.replace(
            temp_path,
            path,
        )

    finally:
        if temp_path.exists():
            temp_path.unlink()


def add_canonical_publication(
    display_name: str,
) -> dict[str, Any]:

    display_name = _clean_name(
        display_name
    )

    if len(display_name) < 2:
        raise ValueError(
            "Enter a publication name first."
        )

    if len(display_name) > 200:
        raise ValueError(
            "Publication name must be "
            "200 characters or fewer."
        )

    LOCK_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with LOCK_PATH.open(
        "a+",
        encoding="utf-8",
    ) as lock_handle:

        fcntl.flock(
            lock_handle.fileno(),
            fcntl.LOCK_EX,
        )

        data = json.loads(
            PUBLICATION_PATH.read_text(
                encoding="utf-8"
            )
        )

        publications = data.get(
            "publications"
        )

        legacy_lookup = data.get(
            "legacy_lookup"
        )

        if not isinstance(
            publications,
            dict,
        ):
            raise ValueError(
                "Canonical publication data has "
                "an invalid 'publications' structure."
            )

        if not isinstance(
            legacy_lookup,
            dict,
        ):
            raise ValueError(
                "Canonical publication data has "
                "an invalid 'legacy_lookup' structure."
            )

        folded_name = (
            display_name.casefold()
        )

        # Already a canonical publication.
        for slug, publication in publications.items():

            if not isinstance(
                publication,
                dict,
            ):
                continue

            existing_name = _clean_name(
                publication.get(
                    "display_name",
                    "",
                )
            )

            if (
                existing_name
                and existing_name.casefold()
                == folded_name
            ):
                return {
                    "created": False,
                    "publication": {
                        "slug": slug,
                        "display_name": existing_name,
                    },
                }

        # Already known as an exact legacy publication value.
        for (
            legacy_name,
            mapped_slug,
        ) in legacy_lookup.items():

            if (
                str(legacy_name).casefold()
                != folded_name
            ):
                continue

            existing = publications.get(
                str(mapped_slug)
            )

            if isinstance(existing, dict):
                return {
                    "created": False,
                    "publication": {
                        "slug": str(mapped_slug),
                        "display_name": _clean_name(
                            existing.get(
                                "display_name",
                                display_name,
                            )
                        ),
                    },
                }

        base_slug = _slugify(
            display_name
        )

        slug = base_slug
        suffix = 2

        while slug in publications:
            slug = (
                f"{base_slug}-{suffix}"
            )
            suffix += 1

        # Append only the new entry.
        # Do not reorder existing canonical records.
        publications[slug] = {
            "slug": slug,
            "display_name": display_name,
            "retain_legacy_as_detail": True,
            "aliases": [],
        }

        # Likewise, append only this new lookup.
        legacy_lookup[display_name] = slug

        _write_atomic(
            PUBLICATION_PATH,
            data,
        )

        return {
            "created": True,
            "publication": {
                "slug": slug,
                "display_name": display_name,
            },
        }
