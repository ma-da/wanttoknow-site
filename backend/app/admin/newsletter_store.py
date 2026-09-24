from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
DRAFT_DIR = BACKEND_DIR / "var" / "newsletter-drafts"

ISSUE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def validate_issue_date(issue_date: str) -> str:
    issue_date = str(issue_date).strip()

    if not ISSUE_DATE_RE.fullmatch(issue_date):
        raise ValueError("Newsletter issue date must use YYYY-MM-DD")

    try:
        datetime.strptime(issue_date, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("Invalid newsletter issue date") from exc

    return issue_date


def draft_path(issue_date: str) -> Path:
    issue_date = validate_issue_date(issue_date)
    return DRAFT_DIR / f"{issue_date}.json"


def empty_newsletter(issue_date: str) -> dict[str, Any]:
    issue_date = validate_issue_date(issue_date)
    now = utc_now()

    return {
        "schema_version": 1,
        "newsletter_id": issue_date,
        "issue_date": issue_date,
        "status": "draft",
        "title": "",
        "headlines": ["", "", ""],
        "regular_preview_items": [],
        "inspiring_preview_items": [],
        "special_note_markdown": "",
        "regular_article_ids": [],
        "inspiring_article_ids": [],
        "created_at": now,
        "updated_at": now,
    }


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]


def _article_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    result: list[str] = []
    seen: set[str] = set()

    for item in value:
        article_id = str(item).strip()

        if not article_id:
            continue

        if not article_id.isdigit():
            raise ValueError(f"Invalid article ID: {article_id}")

        if article_id in seen:
            continue

        seen.add(article_id)
        result.append(article_id)

    return result


def normalize_newsletter(
    issue_date: str,
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_date = validate_issue_date(issue_date)
    existing = existing or empty_newsletter(issue_date)

    headlines = payload.get("headlines", existing.get("headlines", []))
    headlines = [str(value).strip() for value in headlines] if isinstance(headlines, list) else []
    headlines = (headlines + ["", "", ""])[:3]

    regular_ids = _article_ids(
        payload.get("regular_article_ids", existing.get("regular_article_ids", []))
    )
    inspiring_ids = _article_ids(
        payload.get("inspiring_article_ids", existing.get("inspiring_article_ids", []))
    )

    overlap = set(regular_ids) & set(inspiring_ids)
    if overlap:
        raise ValueError(
            "Article cannot appear in both newsletter sections: "
            + ", ".join(sorted(overlap))
        )

    return {
        "schema_version": 1,
        "newsletter_id": issue_date,
        "issue_date": issue_date,
        "status": str(payload.get("status", existing.get("status", "draft"))).strip() or "draft",
        "title": str(payload.get("title", existing.get("title", ""))).strip(),
        "headlines": headlines,
        "regular_preview_items": _text_list(
            payload.get(
                "regular_preview_items",
                existing.get("regular_preview_items", []),
            )
        ),
        "inspiring_preview_items": _text_list(
            payload.get(
                "inspiring_preview_items",
                existing.get("inspiring_preview_items", []),
            )
        ),
        "special_note_markdown": str(
            payload.get(
                "special_note_markdown",
                existing.get("special_note_markdown", ""),
            )
        ).strip(),
        "regular_article_ids": regular_ids,
        "inspiring_article_ids": inspiring_ids,
        "created_at": existing.get("created_at") or utc_now(),
        "updated_at": utc_now(),
    }


def load_newsletter(issue_date: str) -> dict[str, Any]:
    path = draft_path(issue_date)

    if not path.exists():
        return empty_newsletter(issue_date)

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Newsletter draft JSON must contain an object")

    return normalize_newsletter(issue_date, data, existing=data)


def save_newsletter(
    issue_date: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)

    path = draft_path(issue_date)
    existing = load_newsletter(issue_date) if path.exists() else None
    data = normalize_newsletter(issue_date, payload, existing=existing)

    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)

    return data


def delete_newsletter(issue_date: str) -> bool:
    path = draft_path(issue_date)

    if not path.exists():
        return False

    path.unlink()
    return True


def list_newsletters() -> list[dict[str, Any]]:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)

    results = []

    for path in sorted(DRAFT_DIR.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            results.append(
                {
                    "newsletter_id": data.get("newsletter_id", path.stem),
                    "issue_date": data.get("issue_date", path.stem),
                    "title": data.get("title", ""),
                    "status": data.get("status", "draft"),
                    "updated_at": data.get("updated_at", ""),
                }
            )
        except Exception:
            continue

    return results
