from __future__ import annotations

import fcntl
import gzip
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .article_query import admin_db_path, default_repo_root
from .article_store import article_hash, compact_json, file_sha256, row_to_article, utc_now, validate_article
from .article_withdrawal import ensure_withdrawal_schema
from .image_staging import ensure_image_schema, image_staging_root
from .git_publish import (
    GitPublishError,
    append_publish_event,
    commit_and_push_dev,
    ensure_dev_checkpoint,
    reset_to_checkpoint,
    revert_pushed_commit,
)

PUBLISH_SCRIPTS = (
    "build-news-derived.py",
    "build-news-articles.py",
    "build-category-pages.py",
    "build-topic-pages.py",
)
DERIVED_FILES = (
    "article-related-24.json",
    "article-related-24-with-scores.json",
    "article-index.jsonl",
    "archive_stats.json",
)
ROUTING_FILE = "news-withdrawals.json"


class PublishError(RuntimeError):
    pass


def publish_root() -> Path:
    configured = os.environ.get("WTK_PUBLISH_ROOT")
    return Path(configured).expanduser().resolve() if configured else default_repo_root().resolve()


def publish_runs_root() -> Path:
    configured = os.environ.get("WTK_PUBLISH_RUNS_DIR")
    return Path(configured).expanduser().resolve() if configured else publish_root() / "backend/var/publish-runs"


def _master_path(root: Path) -> Path:
    return root / "src/site/data/wtk_articles_master.jsonl"


def ensure_publish_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS article_publish_runs (
            run_id TEXT PRIMARY KEY,
            scope TEXT NOT NULL CHECK(scope IN ('article', 'batch')),
            batch_id INTEGER,
            started_at TEXT NOT NULL,
            started_by TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL CHECK(status IN ('running', 'published', 'failed')),
            article_ids_json TEXT NOT NULL,
            published_count INTEGER NOT NULL DEFAULT 0,
            withdrawal_count INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX IF NOT EXISTS idx_article_publish_runs_started
            ON article_publish_runs(started_at DESC);
        """
    )


@contextmanager
def _publication_lock(root: Path):
    lock_path = root / "backend/var/article-publish.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PublishError("Another article publication is already running") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PublishError(f"Required file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PublishError(f"Invalid JSON: {path}: {exc}") from exc


def _load_master(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    try:
        handle = path.open("r", encoding="utf-8")
    except FileNotFoundError as exc:
        raise PublishError(f"Canonical master not found: {path}") from exc
    with handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                article = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PublishError(f"Invalid JSON in canonical master line {line_no}: {exc}") from exc
            validate_article(article, line_no)
            aid = article["article_id"]
            slug = article["slug"]
            if aid in seen_ids:
                raise PublishError(f"Duplicate article ID in canonical master: {aid}")
            if slug in seen_slugs:
                raise PublishError(f"Duplicate article slug in canonical master: {slug}")
            seen_ids.add(aid)
            seen_slugs.add(slug)
            records.append(article)
    if not records:
        raise PublishError("Canonical article master is empty")
    return records


def _valid_http_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def _validate_publishable(
    article: dict[str, Any],
    *,
    canonical_before: dict[str, Any] | None,
    categories: dict[str, Any],
    publications: dict[str, Any],
) -> list[str]:
    validate_article(article)
    aid = article["article_id"]
    required_text = (
        "title", "slug", "path", "url", "publication_date", "posted_date",
        "publication_group", "publication_name", "summary_markdown",
    )
    missing = [field for field in required_text if not str(article[field]).strip()]
    if missing:
        raise PublishError(f"Article {aid} is not ready to publish; missing: {', '.join(missing)}")
    if not article["tags"]:
        raise PublishError(f"Article {aid} is not ready to publish; choose at least one category")
    try:
        date.fromisoformat(article["publication_date"])
        date.fromisoformat(article["posted_date"])
    except ValueError as exc:
        raise PublishError(f"Article {aid} has an invalid publication or posted date") from exc
    if article["path"] != f"/news/{article['slug']}":
        raise PublishError(f"Article {aid} path does not match its slug")
    if article["url"] != f"https://www.wanttoknow.info/news/{article['slug']}":
        raise PublishError(f"Article {aid} canonical URL does not match its slug")
    if article["publication_group"] not in publications:
        raise PublishError(f"Article {aid} uses an unknown canonical publication")
    expected_name = str(publications[article["publication_group"]].get("display_name") or article["publication_group"])
    if article["publication_name"] != expected_name:
        raise PublishError(f"Article {aid} publication display name is out of sync")
    unknown_tags = sorted(set(article["tags"]) - set(categories))
    if unknown_tags:
        raise PublishError(f"Article {aid} uses unknown categories: {', '.join(unknown_tags)}")
    if not 0 <= article["priority"] <= 1000:
        raise PublishError(f"Article {aid} priority must be between 0 and 1000")

    warnings: list[str] = []
    source_url = article["source_url"].strip()
    before_url = str((canonical_before or {}).get("source_url") or "").strip()
    if canonical_before is None:
        if not _valid_http_url(source_url):
            raise PublishError(f"Article {aid} needs a valid Source URL before publication")
    elif source_url != before_url:
        if not _valid_http_url(source_url):
            raise PublishError(f"Article {aid} changed Source URL must be valid http:// or https://")
    elif source_url and not _valid_http_url(source_url):
        warnings.append(f"Article {aid} retains a legacy malformed Source URL")

    filename = article["image_filename"].strip()
    image_path = article["image_path"].strip()
    if bool(filename) != bool(image_path):
        raise PublishError(f"Article {aid} image filename/path are inconsistent")
    if filename:
        if filename != f"{aid}i.jpg" or image_path != f"/assets/images/article-images/{aid}i.jpg":
            raise PublishError(f"Article {aid} image fields do not follow the canonical filename convention")
    return warnings


def _selected_rows(conn: sqlite3.Connection, article_ids: Iterable[int]) -> list[sqlite3.Row]:
    ids = sorted({int(x) for x in article_ids})
    if not ids:
        raise PublishError("No draft articles were selected for publication")
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM articles WHERE article_id IN ({placeholders}) ORDER BY source_order",
        ids,
    ).fetchall()
    found = {int(row["article_id"]) for row in rows}
    missing = [x for x in ids if x not in found]
    if missing:
        raise PublishError("Article not found: " + ", ".join(map(str, missing)))
    for row in rows:
        if row["workflow_state"] not in {"draft", "ready"}:
            raise PublishError(f"Article {row['article_id']} is already published")
    return rows


def _pending_withdrawals(conn: sqlite3.Connection, article_ids: set[int]) -> dict[int, sqlite3.Row]:
    ensure_withdrawal_schema(conn)
    if not article_ids:
        return {}
    placeholders = ",".join("?" for _ in article_ids)
    rows = conn.execute(
        f"SELECT * FROM article_withdrawals WHERE status='pending' AND article_id IN ({placeholders})",
        sorted(article_ids),
    ).fetchall()
    return {int(row["article_id"]): row for row in rows}


def _staged_images(conn: sqlite3.Connection, article_ids: set[int]) -> dict[int, sqlite3.Row]:
    ensure_image_schema(conn)
    if not article_ids:
        return {}
    placeholders = ",".join("?" for _ in article_ids)
    rows = conn.execute(
        f"SELECT * FROM article_image_staging WHERE article_id IN ({placeholders})",
        sorted(article_ids),
    ).fetchall()
    return {int(row["article_id"]): row for row in rows}


def _assert_selection_unchanged(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    withdrawals: dict[int, sqlite3.Row],
    staged: dict[int, sqlite3.Row],
) -> None:
    for snapshot in rows:
        aid = int(snapshot["article_id"])
        current = conn.execute("SELECT * FROM articles WHERE article_id=?", (aid,)).fetchone()
        if current is None:
            raise PublishError(f"Article {aid} changed while publication was building; retry publication")
        if article_hash(row_to_article(current)) != article_hash(row_to_article(snapshot)):
            raise PublishError(f"Article {aid} was edited while publication was building; retry publication")
        if (current["edit_state"], current["workflow_state"], current["active_batch_id"]) != (
            snapshot["edit_state"], snapshot["workflow_state"], snapshot["active_batch_id"]
        ):
            raise PublishError(f"Article {aid} workflow state changed while publication was building; retry publication")

        current_w = conn.execute(
            "SELECT withdrawal_id,status FROM article_withdrawals WHERE article_id=? AND status='pending' ORDER BY withdrawal_id DESC LIMIT 1",
            (aid,),
        ).fetchone()
        expected_w = withdrawals.get(aid)
        if (current_w is None) != (expected_w is None):
            raise PublishError(f"Article {aid} withdrawal state changed while publication was building; retry publication")
        if current_w is not None and int(current_w["withdrawal_id"]) != int(expected_w["withdrawal_id"]):
            raise PublishError(f"Article {aid} withdrawal request changed while publication was building; retry publication")

        current_stage = conn.execute(
            "SELECT generation FROM article_image_staging WHERE article_id=?", (aid,)
        ).fetchone()
        expected_stage = staged.get(aid)
        if (current_stage is None) != (expected_stage is None):
            raise PublishError(f"Article {aid} staged image changed while publication was building; retry publication")
        if current_stage is not None and str(current_stage["generation"]) != str(expected_stage["generation"]):
            raise PublishError(f"Article {aid} staged image changed while publication was building; retry publication")


def _build_candidate(
    canonical: list[dict[str, Any]],
    rows: list[sqlite3.Row],
    withdrawals: dict[int, sqlite3.Row],
    *,
    categories: dict[str, Any],
    publications: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], list[str], set[str]]:
    canonical_by_id = {int(a["article_id"]): a for a in canonical}
    selected = {int(row["article_id"]): row for row in rows}
    warnings: list[str] = []
    old_slugs_to_remove: set[str] = set()
    replacements: dict[int, dict[str, Any]] = {}

    for aid, row in selected.items():
        before = canonical_by_id.get(aid)
        if aid in withdrawals:
            if before is None:
                raise PublishError(f"Withdrawal article {aid} is not in the canonical master")
            old_slugs_to_remove.add(before["slug"])
            continue
        article = row_to_article(row)
        warnings.extend(
            _validate_publishable(
                article,
                canonical_before=before,
                categories=categories,
                publications=publications,
            )
        )
        if before and before["slug"] != article["slug"]:
            old_slugs_to_remove.add(before["slug"])
        replacements[aid] = article

    candidate: list[dict[str, Any]] = []
    for article in canonical:
        aid = int(article["article_id"])
        if aid in withdrawals:
            continue
        candidate.append(replacements.pop(aid, article))

    new_rows = [row for aid, row in selected.items() if aid in replacements]
    new_rows.sort(key=lambda row: int(row["source_order"]))
    for row in new_rows:
        candidate.append(replacements.pop(int(row["article_id"])))
    if replacements:
        raise PublishError("Unable to order one or more new articles in the candidate master")

    seen_ids: set[str] = set()
    seen_slugs: set[str] = set()
    for article in candidate:
        validate_article(article)
        aid = article["article_id"]
        slug = article["slug"]
        if not slug or "/" in slug or "\\" in slug or "\x00" in slug or slug in {".", ".."}:
            raise PublishError(f"Candidate master contains unsafe slug {slug!r}")
        if aid in seen_ids:
            raise PublishError(f"Candidate master contains duplicate article ID {aid}")
        if slug in seen_slugs:
            raise PublishError(f"Candidate master contains duplicate slug {slug}")
        seen_ids.add(aid)
        seen_slugs.add(slug)
    candidate_slugs = {article["slug"] for article in candidate}
    old_slugs_to_remove.difference_update(candidate_slugs)
    return candidate, canonical_by_id, warnings, old_slugs_to_remove


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(compact_json(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _routing_manifest(conn: sqlite3.Connection, selected_withdrawals: dict[int, sqlite3.Row]) -> list[dict[str, Any]]:
    ensure_withdrawal_schema(conn)
    rows = conn.execute(
        "SELECT * FROM article_withdrawals WHERE status = 'removed' ORDER BY withdrawal_id"
    ).fetchall()
    combined = list(rows) + list(selected_withdrawals.values())
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in combined:
        try:
            canonical = json.loads(row["canonical_article_json"])
        except Exception:
            continue
        path = str(canonical.get("path") or "").strip()
        if not path or path in seen:
            continue
        seen.add(path)
        redirect = str(row["redirect_path"] or "").strip()
        result.append({
            "article_id": str(row["article_id"]),
            "path": path,
            "status": 301 if redirect else 410,
            "redirect_path": redirect,
        })
    return result


def _prepare_workspace_images(
    root: Path,
    site_dst: Path,
    staged: dict[int, sqlite3.Row],
    withdrawals: dict[int, sqlite3.Row],
) -> None:
    """Make article images visible to builders without copying the raw upload.

    Existing published images are hard-linked into the private workspace when
    possible (copy fallback). Staged images are already-normalized JPEGs and
    replace the corresponding workspace links before static pages are built.
    """
    live_images = root / "src/site/assets/images"
    work_images = site_dst / "assets/images"

    groups = (
        ("article-images", "*i.jpg"),
        ("article-thumbs", "*-thumb.jpg"),
    )

    for group, pattern in groups:
        src_dir = live_images / group
        dst_dir = work_images / group
        dst_dir.mkdir(parents=True, exist_ok=True)
        if not src_dir.exists():
            continue
        for src in src_dir.glob(pattern):
            if not src.is_file():
                continue
            dst = dst_dir / src.name
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

    for aid, stage in staged.items():
        if aid in withdrawals:
            continue
        generation = str(stage["generation"])
        stage_root = image_staging_root() / str(aid) / generation
        pairs = (
            (stage_root / f"{aid}i.jpg", work_images / "article-images" / f"{aid}i.jpg"),
            (stage_root / f"{aid}-thumb.jpg", work_images / "article-thumbs" / f"{aid}-thumb.jpg"),
        )
        for src, dst in pairs:
            if not src.is_file():
                raise PublishError(f"Staged image file is missing for article {aid}: {src.name}")
            if dst.exists():
                dst.unlink()
            shutil.copy2(src, dst)


def _prepare_workspace(
    root: Path,
    run_dir: Path,
    candidate: list[dict[str, Any]],
    old_slugs_to_remove: set[str],
    routing: list[dict[str, Any]],
    staged: dict[int, sqlite3.Row],
    withdrawals: dict[int, sqlite3.Row],
) -> tuple[Path, Path]:
    workspace = run_dir / "workspace"
    scripts_dst = workspace / "scripts"
    site_dst = workspace / "src/site"
    data_dst = site_dst / "data"
    news_dst = site_dst / "news"
    scripts_dst.mkdir(parents=True, exist_ok=True)
    data_dst.mkdir(parents=True, exist_ok=True)

    for name in PUBLISH_SCRIPTS:
        src = root / "scripts" / name
        if not src.is_file():
            raise PublishError(f"Required publication builder not found: {src}")
        shutil.copy2(src, scripts_dst / name)

    category_map = root / "src/site/data/news-category-map.json"
    if not category_map.is_file():
        raise PublishError(f"Category map not found: {category_map}")
    shutil.copy2(category_map, data_dst / category_map.name)

    current_news = root / "src/site/news"
    if current_news.exists():
        shutil.copytree(current_news, news_dst)
    else:
        news_dst.mkdir(parents=True, exist_ok=True)

    # Builders determine image presence from files under the project root.
    # Populate the private workspace before rendering so both existing and
    # newly-staged images are visible while HTML is generated.
    _prepare_workspace_images(root, site_dst, staged, withdrawals)

    _write_jsonl(data_dst / "wtk_articles_master.jsonl", candidate)
    (data_dst / ROUTING_FILE).write_text(
        json.dumps(routing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    log_path = run_dir / "build.log"
    commands = (
        [sys.executable, str(scripts_dst / "build-news-derived.py")],
        [sys.executable, str(scripts_dst / "build-news-articles.py"), "--all"],
        [sys.executable, str(scripts_dst / "build-category-pages.py")],
        [sys.executable, str(scripts_dst / "build-topic-pages.py")],
    )
    with log_path.open("w", encoding="utf-8") as log:
        for command in commands:
            log.write("$ " + " ".join(command) + "\n")
            log.flush()
            proc = subprocess.run(
                command,
                cwd=workspace,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            if proc.returncode != 0:
                raise PublishError(f"Publication builder failed: {Path(command[1]).name}. See {log_path}")

    for slug in old_slugs_to_remove:
        stale = news_dst / f"{slug}.html"
        if stale.exists():
            stale.unlink()

    for name in DERIVED_FILES:
        if not (data_dst / name).is_file():
            raise PublishError(f"Publication builder did not produce {name}")
    expected_pages = {a["slug"] for a in candidate}
    missing = [slug for slug in expected_pages if not (news_dst / f"{slug}.html").is_file()]
    if missing:
        raise PublishError(f"Static article generation incomplete; missing {len(missing)} page(s)")

    candidate_by_id = {int(article["article_id"]): article for article in candidate}
    for aid in staged:
        if aid in withdrawals:
            continue
        article = candidate_by_id.get(aid)
        if article is None:
            raise PublishError(f"Staged image article {aid} is missing from the candidate master")
        page = news_dst / f"{article['slug']}.html"
        expected_image = f"/assets/images/article-images/{aid}i.jpg"
        html = page.read_text(encoding="utf-8", errors="replace")
        if expected_image not in html:
            raise PublishError(
                f"Generated article {aid} does not reference its staged image; publication aborted"
            )

    return workspace, log_path


def _atomic_replace_file(src: Path, dst: Path, backup_dir: Path, rollback: list[tuple[str, Path, Path | None]]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup: Path | None = None
    if dst.exists():
        backup = backup_dir / dst.name
        backup.parent.mkdir(parents=True, exist_ok=True)
        os.replace(dst, backup)
    temp = dst.with_name(f".{dst.name}.{secrets.token_hex(6)}.publish")
    try:
        shutil.copy2(src, temp)
        os.replace(temp, dst)
    except Exception:
        try:
            if temp.exists():
                temp.unlink()
            if backup and backup.exists():
                os.replace(backup, dst)
        finally:
            raise
    rollback.append(("file", dst, backup))


def _promote(
    root: Path,
    run_dir: Path,
    workspace: Path,
    staged: dict[int, sqlite3.Row],
    withdrawals: dict[int, sqlite3.Row],
    canonical_by_id: dict[int, dict[str, Any]],
) -> list[tuple[str, Path, Path | None]]:
    rollback: list[tuple[str, Path, Path | None]] = []
    backup = run_dir / "rollback"
    try:
        live_news = root / "src/site/news"
        staged_news = workspace / "src/site/news"
        old_news = backup / "news"
        old_news.parent.mkdir(parents=True, exist_ok=True)
        had_live_news = live_news.exists()
        if had_live_news:
            os.replace(live_news, old_news)
        rollback.append(("dir", live_news, old_news if had_live_news else None))
        os.replace(staged_news, live_news)

        data_src = workspace / "src/site/data"
        data_live = root / "src/site/data"
        for name in ("wtk_articles_master.jsonl", *DERIVED_FILES, ROUTING_FILE):
            _atomic_replace_file(data_src / name, data_live / name, backup / "data", rollback)

        staged_topics = workspace / "src/site/topics"
        if staged_topics.exists():
            for src in staged_topics.glob("*/index.html"):
                dst = root / "src/site/topics" / src.parent.name / "index.html"
                _atomic_replace_file(src, dst, backup / "topics" / src.parent.name, rollback)

        full_dir = root / "src/site/assets/images/article-images"
        thumb_dir = root / "src/site/assets/images/article-thumbs"
        for aid, stage in staged.items():
            if aid in withdrawals:
                continue
            generation = str(stage["generation"])
            stage_root = image_staging_root() / str(aid) / generation
            _atomic_replace_file(stage_root / f"{aid}i.jpg", full_dir / f"{aid}i.jpg", backup / "images/full", rollback)
            _atomic_replace_file(stage_root / f"{aid}-thumb.jpg", thumb_dir / f"{aid}-thumb.jpg", backup / "images/thumb", rollback)

        for aid in withdrawals:
            canonical = canonical_by_id.get(aid) or {}
            if canonical.get("image_filename"):
                for dst, group in (
                    (full_dir / f"{aid}i.jpg", "full"),
                    (thumb_dir / f"{aid}-thumb.jpg", "thumb"),
                ):
                    if dst.exists():
                        b = backup / "removed-images" / group / dst.name
                        b.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(dst, b)
                        rollback.append(("removed", dst, b))
        return rollback
    except Exception:
        _rollback(rollback)
        raise


def _rollback(actions: list[tuple[str, Path, Path | None]]) -> None:
    for kind, dst, backup in reversed(actions):
        try:
            if kind == "dir":
                if dst.exists():
                    failed = dst.with_name(dst.name + ".failed-publish")
                    if failed.exists():
                        shutil.rmtree(failed, ignore_errors=True)
                    os.replace(dst, failed)
                    shutil.rmtree(failed, ignore_errors=True)
                if backup and backup.exists():
                    os.replace(backup, dst)
            elif kind in {"file", "removed"}:
                if dst.exists():
                    dst.unlink()
                if backup and backup.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, dst)
        except Exception:
            pass


def _finalize_db(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    withdrawals: dict[int, sqlite3.Row],
    staged: dict[int, sqlite3.Row],
    *,
    actor: str,
    batch_id: int | None,
) -> tuple[int, int]:
    now = utc_now()
    published = 0
    removed = 0
    with conn:
        for row in rows:
            aid = int(row["article_id"])
            if aid in withdrawals:
                w = withdrawals[aid]
                conn.execute(
                    "UPDATE article_withdrawals SET status='removed', removed_at=?, removed_by=? WHERE withdrawal_id=?",
                    (now, actor, w["withdrawal_id"]),
                )
                conn.execute("DELETE FROM articles WHERE article_id = ?", (aid,))
                removed += 1
                continue
            current = conn.execute("SELECT * FROM articles WHERE article_id = ?", (aid,)).fetchone()
            if current is None:
                raise PublishError(f"Article {aid} disappeared before SQLite finalization")
            canonical_hash = article_hash(row_to_article(current))
            conn.execute(
                """
                UPDATE articles
                SET canonical_hash=?, edit_state='clean', workflow_state='published',
                    active_batch_id=NULL, admin_updated_at=?, admin_updated_by=?
                WHERE article_id=?
                """,
                (canonical_hash, now, actor, aid),
            )
            if aid in staged:
                conn.execute("DELETE FROM article_image_staging WHERE article_id = ?", (aid,))
            published += 1

        if batch_id is not None:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM articles WHERE active_batch_id=? AND workflow_state IN ('draft','ready')",
                (batch_id,),
            ).fetchone()[0]
            if int(remaining or 0) == 0:
                conn.execute(
                    "UPDATE article_batches SET status='published', updated_at=?, published_at=? WHERE batch_id=?",
                    (now, now, batch_id),
                )
            else:
                conn.execute("UPDATE article_batches SET updated_at=? WHERE batch_id=?", (now, batch_id))
    return published, removed


def _cleanup_staging(article_ids: Iterable[int]) -> None:
    for aid in article_ids:
        shutil.rmtree(image_staging_root() / str(aid), ignore_errors=True)


def _compress_master_backup(root: Path, run_dir: Path) -> None:
    old = run_dir / "rollback/data/wtk_articles_master.jsonl"
    if not old.is_file():
        return
    backups = root / "backend/var/publish-backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"{run_dir.name}-master-before.jsonl.gz"
    with old.open("rb") as src, gzip.open(target, "wb", compresslevel=6) as dst:
        shutil.copyfileobj(src, dst)


def publish_articles(
    conn: sqlite3.Connection,
    article_ids: Iterable[int],
    *,
    actor: str,
    scope: str,
    batch_id: int | None = None,
) -> dict[str, Any]:
    if scope not in {"article", "batch"}:
        raise ValueError("Invalid publication scope")
    root = publish_root()
    master = _master_path(root)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)
    run_dir = publish_runs_root() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    ensure_publish_schema(conn)
    started = utc_now()
    ids = sorted({int(x) for x in article_ids})
    conn.execute(
        "INSERT INTO article_publish_runs(run_id, scope, batch_id, started_at, started_by, status, article_ids_json) VALUES (?, ?, ?, ?, ?, 'running', ?)",
        (run_id, scope, batch_id, started, actor, json.dumps(ids, separators=(",", ":"))),
    )
    conn.commit()

    try:
        with _publication_lock(root):
            # Publication is allowed only from a clean production-admin dev
            # worktree that is already synchronized with GitHub. The no-op push
            # performed here proves the known-good pre-publish state is remote
            # before any source/media mutation begins.
            try:
                git_base_sha = ensure_dev_checkpoint(root)
            except GitPublishError as exc:
                raise PublishError(f"Git pre-publish checkpoint failed: {exc}") from exc

            rows = _selected_rows(conn, ids)
            selected_ids = {int(row["article_id"]) for row in rows}
            withdrawals = _pending_withdrawals(conn, selected_ids)
            staged = _staged_images(conn, selected_ids)
            master_before_sha256 = file_sha256(master)
            canonical = _load_master(master)
            categories = _load_json(root / "src/site/data/news-category-map.json")
            publication_map = _load_json(root / "src/site/data/publication-canonicalization.json")
            publications = publication_map.get("publications") if isinstance(publication_map, dict) else None
            if not isinstance(categories, dict) or not isinstance(publications, dict):
                raise PublishError("Publication/category reference data has an unexpected schema")

            candidate, canonical_by_id, warnings, stale_slugs = _build_candidate(
                canonical,
                rows,
                withdrawals,
                categories=categories,
                publications=publications,
            )
            routing = _routing_manifest(conn, withdrawals)
            workspace, log_path = _prepare_workspace(
                root, run_dir, candidate, stale_slugs, routing, staged, withdrawals
            )
            if file_sha256(master) != master_before_sha256:
                raise PublishError("Canonical master changed while publication was building; retry publication")
            _assert_selection_unchanged(conn, rows, withdrawals, staged)
            rollback = _promote(root, run_dir, workspace, staged, withdrawals, canonical_by_id)

            # Every admin publication creates a small tracked event. This makes
            # image-only publications visible to Git without storing JPEGs in
            # Git: main later authorizes the exact media SHA-256 values that may
            # be deployed. Internal withdrawal reasons remain SQLite-only.
            try:
                media_events: list[dict[str, Any]] = []
                full_dir = root / "src/site/assets/images/article-images"
                thumb_dir = root / "src/site/assets/images/article-thumbs"
                for aid in sorted(selected_ids):
                    if aid in withdrawals:
                        media_events.append({"article_id": str(aid), "action": "remove"})
                        continue
                    if aid not in staged:
                        continue
                    full = full_dir / f"{aid}i.jpg"
                    thumb = thumb_dir / f"{aid}-thumb.jpg"
                    if not full.is_file() or not thumb.is_file():
                        raise PublishError(f"Published media is missing after promotion for article {aid}")
                    media_events.append({
                        "article_id": str(aid),
                        "action": "replace",
                        "full_sha256": file_sha256(full),
                        "thumb_sha256": file_sha256(thumb),
                    })

                append_publish_event(
                    root,
                    {
                        "run_id": run_id,
                        "recorded_at": utc_now(),
                        "scope": scope,
                        "article_ids": [str(x) for x in ids],
                        "withdrawal_ids": [str(x) for x in sorted(withdrawals)],
                        "media": media_events,
                    },
                )

                commit_message = (
                    f"admin publish: article {ids[0]}"
                    if scope == "article" and len(ids) == 1
                    else f"admin publish: batch {batch_id or '-'} ({len(ids)} articles)"
                )
                git_commit_sha = commit_and_push_dev(
                    root,
                    base_sha=git_base_sha,
                    message=commit_message,
                )
            except Exception as exc:
                # Git push failure leaves origin/dev unchanged. Restore tracked
                # files to the checkpoint and use the existing rollback journal
                # for ignored generated/media files. SQLite is still draft.
                try:
                    reset_to_checkpoint(root, git_base_sha)
                except Exception:
                    pass
                _rollback(rollback)
                if isinstance(exc, PublishError):
                    raise
                raise PublishError(f"Git dev publication failed; site working copy rolled back: {exc}") from exc

            try:
                published_count, withdrawal_count = _finalize_db(
                    conn, rows, withdrawals, staged, actor=actor, batch_id=batch_id
                )
            except Exception as finalize_exc:
                # GitHub dev was already advanced, so undo it with a normal
                # revert commit rather than rewriting remote history. Then
                # restore generated/media files from the rollback journal.
                try:
                    revert_pushed_commit(root, git_commit_sha)
                except Exception as revert_exc:
                    raise PublishError(
                        "CRITICAL: Git dev was updated but SQLite finalization failed, "
                        f"and the automatic Git revert also failed: {revert_exc}. "
                        f"Published commit: {git_commit_sha}"
                    ) from finalize_exc
                _rollback(rollback)
                raise

            post_warnings: list[str] = []
            try:
                _cleanup_staging(selected_ids)
            except Exception as exc:
                post_warnings.append(f"Published successfully, but image staging cleanup needs attention: {exc}")
            try:
                _compress_master_backup(root, run_dir)
            except Exception as exc:
                post_warnings.append(f"Published successfully, but compressed master backup failed: {exc}")
            try:
                shutil.rmtree(run_dir / "workspace", ignore_errors=True)
                removed_images = run_dir / "rollback/removed-images"
                preserved_removed = run_dir / "removed-images"
                if removed_images.exists():
                    os.replace(removed_images, preserved_removed)
                shutil.rmtree(run_dir / "rollback", ignore_errors=True)
            except Exception as exc:
                post_warnings.append(f"Published successfully, but run-directory cleanup needs attention: {exc}")

            warnings.extend(post_warnings)
            completed = utc_now()
            message = f"Published {published_count} article(s); removed {withdrawal_count} article(s)."
            if post_warnings:
                message += " Publication completed with cleanup warning(s)."
            try:
                conn.execute(
                    """
                    UPDATE article_publish_runs
                    SET completed_at=?, status='published', published_count=?, withdrawal_count=?, message=?
                    WHERE run_id=?
                    """,
                    (completed, published_count, withdrawal_count, message, run_id),
                )
                conn.commit()
            except Exception as exc:
                warnings.append(f"Publication completed, but publish-run audit update failed: {exc}")

            manifest = {
                "run_id": run_id,
                "scope": scope,
                "batch_id": batch_id,
                "article_ids": ids,
                "published_count": published_count,
                "withdrawal_count": withdrawal_count,
                "warnings": warnings,
                "completed_at": completed,
                "build_log": str(log_path),
                "pre_publish_commit": git_base_sha,
                "dev_commit": git_commit_sha,
            }
            try:
                (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            except Exception as exc:
                warnings.append(f"Publication completed, but run manifest write failed: {exc}")
            return manifest
    except Exception as exc:
        try:
            conn.execute(
                "UPDATE article_publish_runs SET completed_at=?, status='failed', message=? WHERE run_id=?",
                (utc_now(), str(exc)[:2000], run_id),
            )
            conn.commit()
        except Exception:
            pass
        if isinstance(exc, PublishError):
            raise
        raise PublishError(str(exc)) from exc


def publish_article(conn: sqlite3.Connection, article_id: int, *, actor: str) -> dict[str, Any]:
    row = conn.execute("SELECT active_batch_id FROM articles WHERE article_id=?", (article_id,)).fetchone()
    if row is None:
        raise LookupError("Article not found")
    batch_id = int(row["active_batch_id"]) if row["active_batch_id"] is not None else None
    return publish_articles(conn, [article_id], actor=actor, scope="article", batch_id=batch_id)


def publish_current_batch(conn: sqlite3.Connection, *, actor: str) -> dict[str, Any]:
    batch = conn.execute(
        "SELECT batch_id FROM article_batches WHERE status='open' ORDER BY batch_id DESC LIMIT 1"
    ).fetchone()
    if batch is None:
        raise PublishError("There is no open draft batch to publish")
    batch_id = int(batch["batch_id"])
    rows = conn.execute(
        "SELECT article_id FROM articles WHERE active_batch_id=? AND workflow_state IN ('draft','ready') ORDER BY source_order",
        (batch_id,),
    ).fetchall()
    ids = [int(row["article_id"]) for row in rows]
    if not ids:
        raise PublishError("The current batch has no draft articles")
    return publish_articles(conn, ids, actor=actor, scope="batch", batch_id=batch_id)
