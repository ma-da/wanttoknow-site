from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
DRAFT_DIR = BACKEND_DIR / "var" / "newsletter-drafts"

ISSUE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEMPLATE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


class NewsletterConflictError(RuntimeError):
    """Raised when a newsletter changed after an editor session loaded it."""


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


def _template_key(value: Any) -> str:
    key = str(value or "standard").strip() or "standard"
    if not TEMPLATE_KEY_RE.fullmatch(key):
        raise ValueError("Invalid newsletter template key")
    return key


def _editor_article_changes(value: Any) -> dict[str, dict[str, Any]]:
    """Normalize safe publication receipts created by the newsletter editor."""
    if not isinstance(value, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}

    for raw_id, raw_receipt in value.items():
        article_id = str(raw_id).strip()
        if not article_id.isdigit() or not isinstance(raw_receipt, dict):
            continue

        base_hash = str(raw_receipt.get("base_hash", "")).strip()
        after_hash = str(raw_receipt.get("after_hash", "")).strip()
        saved_at = str(raw_receipt.get("saved_at", "")).strip()
        safe_to_publish = bool(raw_receipt.get("safe_to_publish"))

        if not after_hash:
            continue

        result[article_id] = {
            "base_hash": base_hash,
            "after_hash": after_hash,
            "saved_at": saved_at,
            "safe_to_publish": safe_to_publish,
        }

    return result


def empty_newsletter(issue_date: str) -> dict[str, Any]:
    issue_date = validate_issue_date(issue_date)
    now = utc_now()

    return {
        "schema_version": 2,
        "newsletter_id": issue_date,
        "issue_date": issue_date,
        "status": "draft",
        "template_key": "standard",
        "title": "",
        "headlines": ["", "", ""],
        "regular_preview_items": [],
        "inspiring_preview_items": [],
        "special_note_markdown": "",
        "regular_article_ids": [],
        "inspiring_article_ids": [],
        "editor_article_changes": {},
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
    touch_updated_at: bool = True,
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

    selected_ids = set(regular_ids) | set(inspiring_ids)
    receipts = _editor_article_changes(
        payload.get(
            "editor_article_changes",
            existing.get("editor_article_changes", {}),
        )
    )
    receipts = {
        article_id: receipt
        for article_id, receipt in receipts.items()
        if article_id in selected_ids
    }

    previous_updated_at = str(existing.get("updated_at", "")).strip()
    updated_at = utc_now() if touch_updated_at else (previous_updated_at or utc_now())

    return {
        "schema_version": 2,
        "newsletter_id": issue_date,
        "issue_date": issue_date,
        "status": str(payload.get("status", existing.get("status", "draft"))).strip() or "draft",
        "template_key": _template_key(
            payload.get("template_key", existing.get("template_key", "standard"))
        ),
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
        "editor_article_changes": receipts,
        "created_at": existing.get("created_at") or utc_now(),
        "updated_at": updated_at,
    }


def load_newsletter(issue_date: str) -> dict[str, Any]:
    path = draft_path(issue_date)

    if not path.exists():
        return empty_newsletter(issue_date)

    data = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("Newsletter draft JSON must contain an object")

    # Reading must not change the revision token. The editor uses updated_at
    # for optimistic concurrency protection.
    return normalize_newsletter(
        issue_date,
        data,
        existing=data,
        touch_updated_at=False,
    )


def save_newsletter(
    issue_date: str,
    payload: dict[str, Any],
    *,
    expected_updated_at: str | None = None,
) -> dict[str, Any]:
    DRAFT_DIR.mkdir(parents=True, exist_ok=True)

    path = draft_path(issue_date)
    existing = load_newsletter(issue_date) if path.exists() else None

    if expected_updated_at is not None:
        actual = str((existing or {}).get("updated_at", "")).strip()
        expected = str(expected_updated_at).strip()
        if actual != expected:
            raise NewsletterConflictError(
                "This newsletter changed after the editor was opened. "
                "Reload before saving so newer changes are not overwritten."
            )

    data = normalize_newsletter(
        issue_date,
        payload,
        existing=existing,
        touch_updated_at=True,
    )

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
                    "template_key": data.get("template_key", "standard"),
                    "updated_at": data.get("updated_at", ""),
                }
            )
        except Exception:
            continue

    return results
