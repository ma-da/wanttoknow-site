from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_RELATIVE_PATH = Path("src/site/data/newsletters.json")
SEARCH_DB_RELATIVE_PATH = Path(
    "src/site/data/search/wanttoknow-search.sqlite"
)
CURRENT_SITE_ROOT = Path(
    os.getenv("WTK_CURRENT_SITE_ROOT", "/srv/wanttoknow/site")
)

NOTE_HEADING_RE = re.compile(
    r"(?im)(?:^|\n)\s*#{1,6}\s+Note\s*:?[ \t]*(?:\n|$)"
)
NOTE_LABEL_RE = re.compile(
    r"(?im)(?:^|\n)\s*(?:\*\*|__)?Note:(?:\*\*|__)?\s*"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def public_newsletter_path(root: Path | None = None) -> Path:
    return (root or REPO_ROOT) / PUBLIC_RELATIVE_PATH


def search_db_path(root: Path | None = None) -> Path:
    override = os.getenv("WTK_SEARCH_DB", "").strip()
    if override:
        return Path(override).expanduser()

    # The search DB is a derived release artifact. The admin worktree normally
    # does not carry it, so admin-side newsletter publication resolves articles
    # through the active public release. When this module itself runs from the
    # public release, that path naturally resolves to the same database.
    if root is not None:
        explicit = root / SEARCH_DB_RELATIVE_PATH
        if explicit.is_file():
            return explicit

    current = CURRENT_SITE_ROOT / SEARCH_DB_RELATIVE_PATH
    if current.is_file():
        return current

    return REPO_ROOT / SEARCH_DB_RELATIVE_PATH


def _empty_public_data() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "updated_at": "",
        "newsletters": [],
    }


def load_public_newsletters(
    root: Path | None = None,
) -> dict[str, Any]:
    path = public_newsletter_path(root)
    if not path.exists():
        return _empty_public_data()

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Public newsletters JSON must contain an object")

    records = data.get("newsletters", [])
    if not isinstance(records, list):
        raise ValueError("Public newsletters JSON must contain a newsletters array")

    return {
        "schema_version": 1,
        "updated_at": str(data.get("updated_at", "")),
        "newsletters": [item for item in records if isinstance(item, dict)],
    }


def get_public_newsletter(
    newsletter_id: str,
    *,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Return one public newsletter by its stable ID.

    Date-only identifiers from the original archive remain backward compatible:
    if no newsletter_id matches and exactly one record has that issue_date, that
    record is returned. Ambiguous same-day date lookups deliberately return None.
    """
    newsletter_id = str(newsletter_id).strip()
    data = load_public_newsletters(root)

    for record in data["newsletters"]:
        if str(record.get("newsletter_id", "")).strip() == newsletter_id:
            return record

    date_matches = [
        record
        for record in data["newsletters"]
        if str(record.get("issue_date", "")).strip() == newsletter_id
    ]
    if len(date_matches) == 1:
        return date_matches[0]

    return None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _article_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    result: list[str] = []
    seen: set[str] = set()
    for value_item in value:
        article_id = str(value_item).strip()
        if not article_id or not article_id.isdigit() or article_id in seen:
            continue
        seen.add(article_id)
        result.append(article_id)
    return result


def newsletter_article_ids(newsletter: dict[str, Any]) -> list[str]:
    return _article_ids(
        [
            *newsletter.get("regular_article_ids", []),
            *newsletter.get("inspiring_article_ids", []),
        ]
    )


def _decode_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _split_display_markdown(value: str) -> tuple[str, str]:
    """Split preserved news presentation Markdown into summary + WTK Note.

    Search stores presentation Markdown separately from its normalized FTS text.
    Existing article notes use a paragraph-level **Note:** marker, so newsletter
    rendering can retain the same summary/note distinction without exposing the
    private admin SQLite database or loading the complete article master.
    """

    text = str(value or "").strip()
    if not text:
        return "", ""

    heading = NOTE_HEADING_RE.search(text)
    if heading:
        summary = text[: heading.start()].strip()
        note = text[heading.end() :].strip()
        return summary, note

    label = NOTE_LABEL_RE.search(text)
    if label:
        summary = text[: label.start()].strip()
        note = text[label.start() :].strip()
        return summary, note

    return text, ""


def _withdrawn_article(article_id: str) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": f"Article {article_id} no longer available",
        "publication_date": "",
        "publication_name": "",
        "source_url": "",
        "summary_markdown": (
            "*This article is no longer present in the public WantToKnow.info "
            "search corpus. It remains listed here so the newsletter's "
            "historical article order is preserved.*"
        ),
        "note_markdown": "",
    }


def resolve_public_article_records(
    newsletter: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve only the newsletter's selected article IDs from public search DB.

    The public search SQLite database is a derived, read-only representation of
    published content. This intentionally avoids the private admin SQLite working
    copy, so unpublished article drafts can never leak into the public archive.

    Current builds store the original news summary, WTK Note, and source URL in
    content.metadata_json. The display_markdown/text fallbacks keep the archive
    readable during a rolling deployment before the search DB has been rebuilt.
    """

    article_ids = newsletter_article_ids(newsletter)
    if not article_ids:
        return {}

    db_path = search_db_path(root)
    if not db_path.is_file():
        raise FileNotFoundError(f"Search database not found: {db_path}")

    numeric_ids = [int(value) for value in article_ids]
    placeholders = ", ".join("?" for _ in numeric_ids)

    connection = sqlite3.connect(
        f"file:{db_path}?mode=ro",
        uri=True,
        timeout=5.0,
    )
    connection.row_factory = sqlite3.Row

    try:
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(content)").fetchall()
        }
        has_display_markdown = "display_markdown" in columns
        display_column = (
            ", display_markdown"
            if has_display_markdown
            else ""
        )

        rows = connection.execute(
            f"""
            SELECT
                ref_id,
                title,
                url,
                published_at,
                publisher,
                text,
                metadata_json
                {display_column}
            FROM content
            WHERE record_type = 'news'
              AND ref_id IN ({placeholders})
            """,
            numeric_ids,
        ).fetchall()
    finally:
        connection.close()

    records: dict[str, dict[str, Any]] = {}

    for row in rows:
        article_id = str(row["ref_id"])
        metadata = _decode_metadata(row["metadata_json"])

        summary_markdown = str(
            metadata.get("summary_markdown") or ""
        ).strip()
        note_markdown = str(
            metadata.get("note_markdown") or ""
        ).strip()

        if not summary_markdown and has_display_markdown:
            summary_markdown, display_note = _split_display_markdown(
                row["display_markdown"] or ""
            )
            if not note_markdown:
                note_markdown = display_note

        # Old search databases may predate both metadata preservation and the
        # display_markdown column. Plain search text is a last-resort summary
        # fallback until deployment rebuilds the derived database.
        if not summary_markdown:
            summary_markdown = str(row["text"] or "").strip()

        source_url = str(metadata.get("source_url") or "").strip()

        records[article_id] = {
            "article_id": article_id,
            "title": str(row["title"] or "").strip(),
            "publication_date": str(row["published_at"] or "").strip(),
            "publication_name": str(row["publisher"] or "").strip(),
            "source_url": source_url,
            "summary_markdown": summary_markdown,
            "note_markdown": note_markdown,
        }

    for article_id in article_ids:
        records.setdefault(article_id, _withdrawn_article(article_id))

    return records


def public_record_from_draft(
    newsletter: dict[str, Any],
    *,
    existing_public: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_date = str(newsletter.get("issue_date", "")).strip()
    if not issue_date:
        raise ValueError("Newsletter issue date is required")

    regular_ids = _article_ids(newsletter.get("regular_article_ids", []))
    inspiring_ids = _article_ids(newsletter.get("inspiring_article_ids", []))
    if not regular_ids and not inspiring_ids:
        raise ValueError("Newsletter must contain at least one article before publication")

    now = utc_now()
    existing_public = existing_public or {}
    published_at = str(existing_public.get("published_at", "")).strip() or now

    headlines = _text_list(newsletter.get("headlines", []))[:3]
    headlines = (headlines + ["", "", ""])[:3]

    newsletter_id = str(newsletter.get("newsletter_id", "")).strip() or issue_date

    return {
        "schema_version": 1,
        "newsletter_id": newsletter_id,
        "issue_date": issue_date,
        "status": "published",
        "template_key": str(newsletter.get("template_key") or "standard").strip() or "standard",
        "title": str(newsletter.get("title", "")).strip(),
        "headlines": headlines,
        "regular_preview_items": _text_list(
            newsletter.get("regular_preview_items", [])
        ),
        "inspiring_preview_items": _text_list(
            newsletter.get("inspiring_preview_items", [])
        ),
        "special_note_markdown": str(
            newsletter.get("special_note_markdown", "")
        ).strip(),
        "regular_article_ids": regular_ids,
        "inspiring_article_ids": inspiring_ids,
        "browser_url": (
            "https://www.wanttoknow.info/newsletter-archive.html"
            f"?issue={newsletter_id}"
        ),
        "published_at": published_at,
        "updated_at": now,
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _publish_payload(
    newsletter: dict[str, Any],
    *,
    source_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = load_public_newsletters(source_root)
    existing_public = None

    retained: list[dict[str, Any]] = []
    issue_date = str(newsletter.get("issue_date", "")).strip()
    newsletter_id = str(newsletter.get("newsletter_id", "")).strip() or issue_date

    for record in data["newsletters"]:
        record_id = str(record.get("newsletter_id", "")).strip()
        if record_id == newsletter_id:
            existing_public = record
        else:
            retained.append(record)

    public_record = public_record_from_draft(
        newsletter,
        existing_public=existing_public,
    )
    retained.append(public_record)
    retained.sort(
        key=lambda item: (
            str(item.get("issue_date", "")),
            str(item.get("newsletter_id", "")),
        ),
        reverse=True,
    )

    payload = {
        "schema_version": 1,
        "updated_at": public_record["updated_at"],
        "newsletters": retained,
    }
    return payload, public_record


def _mirror_to_current(payload: dict[str, Any], source_root: Path) -> str | None:
    try:
        current_root = CURRENT_SITE_ROOT.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return "Active public release was not found; source JSON was updated only."

    try:
        if current_root == source_root.resolve():
            return None
    except OSError:
        pass

    destination = public_newsletter_path(current_root)
    try:
        _atomic_write_json(destination, payload)
    except OSError as exc:
        raise OSError(
            "Could not mirror newsletters.json to the active public release: "
            f"{exc}"
        ) from exc

    return None


def _best_effort_git_sync(source_root: Path, issue_date: str) -> str | None:
    """Commit/push only newsletters.json when it is the sole worktree change.

    Newsletter publication must never sweep unrelated development work into a
    commit. If anything else is modified/staged/untracked, publication remains
    successful and Git synchronization is deliberately skipped with a warning.
    """

    def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=source_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=check,
        )

    try:
        branch = run("branch", "--show-current").stdout.strip()
        if branch != "dev":
            return f"Git sync skipped because the admin worktree is on {branch or 'detached HEAD'}, not dev."

        status_lines = [
            line
            for line in run("status", "--porcelain=v1", "--untracked-files=all").stdout.splitlines()
            if line.strip()
        ]
        allowed = PUBLIC_RELATIVE_PATH.as_posix()
        other = [line for line in status_lines if line[3:] != allowed]
        if other:
            return "Git sync skipped because the admin worktree has unrelated changes."

        if not status_lines:
            return None

        run("add", "--", allowed)
        staged = run("diff", "--cached", "--name-only").stdout.splitlines()
        if staged != [allowed]:
            run("restore", "--staged", "--", allowed, check=False)
            return "Git sync skipped because unrelated staged changes are present."

        run(
            "commit",
            "--no-gpg-sign",
            "-m",
            f"Publish newsletter {issue_date}",
        )
        push = run(
            "push",
            "--porcelain",
            "origin",
            "HEAD:refs/heads/dev",
            check=False,
        )
        if push.returncode != 0:
            return "Newsletter published, but the Git push to dev failed and needs manual attention."

        return None
    except (OSError, subprocess.SubprocessError) as exc:
        return f"Newsletter published, but Git synchronization could not complete: {exc}"


def publish_newsletter(
    newsletter: dict[str, Any],
    *,
    source_root: Path | None = None,
) -> dict[str, Any]:
    source_root = source_root or REPO_ROOT
    payload, public_record = _publish_payload(
        newsletter,
        source_root=source_root,
    )

    source_path = public_newsletter_path(source_root)
    before = source_path.read_bytes() if source_path.exists() else None

    try:
        _atomic_write_json(source_path, payload)
        mirror_warning = _mirror_to_current(payload, source_root)
    except Exception:
        if before is None:
            source_path.unlink(missing_ok=True)
        else:
            temp = source_path.with_suffix(source_path.suffix + ".rollback")
            temp.write_bytes(before)
            temp.replace(source_path)
        raise

    git_warning = _best_effort_git_sync(source_root, public_record["issue_date"])
    warnings = [warning for warning in [mirror_warning, git_warning] if warning]

    return {
        "record": public_record,
        "warnings": warnings,
        "path": str(source_path),
    }
