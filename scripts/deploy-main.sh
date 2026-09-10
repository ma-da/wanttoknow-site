#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

# WantToKnow.info main -> live atomic deployer.
#
# Run as:
#   sudo /srv/wanttoknow/admin/scripts/deploy-main.sh
#
# The script NEVER deploys the admin worktree itself. It fetches origin/main,
# archives the exact remote commit, builds a fresh release, then atomically
# switches /srv/wanttoknow/current.

ADMIN_ROOT="/srv/wanttoknow/admin"
RELEASES_ROOT="/srv/wanttoknow/releases"
DEPLOY_ROOT="/srv/wanttoknow/deploy"
RUNTIME_ROOT="/srv/wanttoknow/runtime"
CURRENT_LINK="/srv/wanttoknow/current"

ADMIN_USER="wtkadmin"
ADMIN_GROUP="wtk-admin"
SERVICE="wanttoknow.service"
BUILD_PYTHON="${ADMIN_ROOT}/.venv/bin/python"
RUNTIME_PYTHON="${RUNTIME_ROOT}/.venv/bin/python"

PUBLIC_HOST="${WTK_DEPLOY_HOST:-new.wanttoknow.info}"
LOCK_FILE="/run/lock/wanttoknow-main-deploy.lock"

SWITCHED=0
PREVIOUS_TARGET=""
RELEASE_DIR=""
DEPLOY_LOG=""

say() {
    printf '\n[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

die() {
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

as_admin() {
    runuser -u "${ADMIN_USER}" -- "$@"
}

restore_previous() {
    if [[ "${SWITCHED}" != "1" || -z "${PREVIOUS_TARGET}" ]]; then
        return 0
    fi

    say "Smoke test failed; restoring previous release"
    local rollback_link="${CURRENT_LINK}.rollback.$$"
    rm -f "${rollback_link}"
    ln -s "${PREVIOUS_TARGET}" "${rollback_link}"
    mv -Tf "${rollback_link}" "${CURRENT_LINK}"
    systemctl restart "${SERVICE}" || true
    SWITCHED=0

    printf 'ROLLBACK target=%s\n' "${PREVIOUS_TARGET}" >&2
}

cleanup_on_exit() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        restore_previous || true

        if [[ "${SWITCHED}" != "1" && -n "${RELEASE_DIR}" && -d "${RELEASE_DIR}" ]]; then
            rm -rf "${RELEASE_DIR}" || true
        fi

        if [[ -n "${DEPLOY_LOG}" ]]; then
            printf '\nDeployment failed. Log: %s\n' "${DEPLOY_LOG}" >&2
        fi
    fi
}
trap cleanup_on_exit EXIT
trap 'exit 130' INT TERM

[[ "${EUID}" -eq 0 ]] || die "Run this script with sudo."

for cmd in git tar curl flock runuser systemctl python3 rsync; do
    command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
done

[[ -d "${ADMIN_ROOT}/.git" ]] || die "Admin Git worktree not found: ${ADMIN_ROOT}"
[[ -x "${BUILD_PYTHON}" ]] || die "Admin build Python not found: ${BUILD_PYTHON}"
[[ -x "${RUNTIME_PYTHON}" ]] || die "Durable runtime Python not found: ${RUNTIME_PYTHON}"
[[ -L "${CURRENT_LINK}" ]] || die "${CURRENT_LINK} must already be a symlink"

mkdir -p "${RELEASES_ROOT}" "${DEPLOY_ROOT}/logs"

exec 9>"${LOCK_FILE}"
flock -n 9 || die "Another WantToKnow deployment is already running."

say "Fetching origin/main"
as_admin git -C "${ADMIN_ROOT}" fetch --quiet --prune origin main

MAIN_SHA="$(as_admin git -C "${ADMIN_ROOT}" rev-parse --verify origin/main)"
MAIN_SHORT="${MAIN_SHA:0:12}"
MAIN_SUBJECT="$(as_admin git -C "${ADMIN_ROOT}" show -s --format=%s "${MAIN_SHA}")"

[[ "${MAIN_SHA}" =~ ^[0-9a-f]{40}$ ]] || die "Unable to resolve a valid origin/main commit"

PREVIOUS_TARGET="$(readlink -f "${CURRENT_LINK}")"
[[ -d "${PREVIOUS_TARGET}" ]] || die "Current release target does not exist: ${PREVIOUS_TARGET}"

if [[ -f "${PREVIOUS_TARGET}/.wtk-release.json" ]]; then
    DEPLOYED_SHA="$(
        python3 - "${PREVIOUS_TARGET}/.wtk-release.json" <<'PY'
import json
import sys
from pathlib import Path

try:
    print(json.loads(Path(sys.argv[1]).read_text())["main_sha"])
except Exception:
    print("")
PY
    )"

    if [[ "${DEPLOYED_SHA}" == "${MAIN_SHA}" ]]; then
        say "origin/main ${MAIN_SHORT} is already deployed"
        exit 0
    fi
fi

STAMP="$(date -u '+%Y%m%dT%H%M%SZ')"
RELEASE_ID="${STAMP}-${MAIN_SHORT}"
RELEASE_DIR="${RELEASES_ROOT}/${RELEASE_ID}"
DEPLOY_LOG="${DEPLOY_ROOT}/logs/${RELEASE_ID}.log"

[[ ! -e "${RELEASE_DIR}" ]] || die "Release already exists: ${RELEASE_DIR}"

say "Preparing release ${RELEASE_ID}"
mkdir -p "${RELEASE_DIR}"
chown "${ADMIN_USER}:${ADMIN_GROUP}" "${RELEASE_DIR}"

ARCHIVE="${RELEASE_DIR}/.source.tar"
rm -f "${ARCHIVE}"

as_admin git -C "${ADMIN_ROOT}" archive \
    --format=tar \
    --output="${ARCHIVE}" \
    "${MAIN_SHA}"

tar -xf "${ARCHIVE}" -C "${RELEASE_DIR}"
rm -f "${ARCHIVE}"

chown -R "${ADMIN_USER}:${ADMIN_GROUP}" "${RELEASE_DIR}"

# ---------------------------------------------------------------------------
# Durable media
# ---------------------------------------------------------------------------
# Article images are a single live media library. Builders can inspect them
# through release-local symlinks, but no bytes are copied into a release.
#
# MKULTRA images/thumbs are also large ignored media collections. If present
# in the durable admin workspace, release-local symlinks avoid multi-GB copies.

link_durable_dir() {
    local source="$1"
    local destination="$2"

    [[ -d "${source}" ]] || return 0

    mkdir -p "$(dirname "${destination}")"

    if [[ -e "${destination}" || -L "${destination}" ]]; then
        rm -rf "${destination}"
    fi

    ln -s "${source}" "${destination}"
    chown -h "${ADMIN_USER}:${ADMIN_GROUP}" "${destination}"
}

link_durable_dir \
    "${ADMIN_ROOT}/src/site/assets/images/article-images" \
    "${RELEASE_DIR}/src/site/assets/images/article-images"

link_durable_dir \
    "${ADMIN_ROOT}/src/site/assets/images/article-thumbs" \
    "${RELEASE_DIR}/src/site/assets/images/article-thumbs"

link_durable_dir \
    "${ADMIN_ROOT}/src/site/search/mkultra/images" \
    "${RELEASE_DIR}/src/site/search/mkultra/images"

link_durable_dir \
    "${ADMIN_ROOT}/src/site/search/mkultra/thumbs" \
    "${RELEASE_DIR}/src/site/search/mkultra/thumbs"

# ---------------------------------------------------------------------------
# Search artifacts
# ---------------------------------------------------------------------------
# Search is release-local and fully derived from Git-held source. Do not copy
# SQLite/related-content artifacts forward from the previous release.

# ---------------------------------------------------------------------------
# Rebuild article and search derived outputs from the exact origin/main source.
# ---------------------------------------------------------------------------

: > "${DEPLOY_LOG}"
chown "${ADMIN_USER}:${ADMIN_GROUP}" "${DEPLOY_LOG}"

run_builder() {
    say "Running $*"
    as_admin "${BUILD_PYTHON}" "$@" >>"${DEPLOY_LOG}" 2>&1
}

run_builder "${RELEASE_DIR}/scripts/build-news-derived.py"
run_builder "${RELEASE_DIR}/scripts/build-search-corpus.py"
run_builder "${RELEASE_DIR}/scripts/build-search-db.py"
run_builder "${RELEASE_DIR}/scripts/build-related-map.py"
run_builder "${RELEASE_DIR}/scripts/build-news-articles.py" --all
run_builder "${RELEASE_DIR}/scripts/build-category-pages.py"
run_builder "${RELEASE_DIR}/scripts/build-topic-pages.py"

# ---------------------------------------------------------------------------
# Candidate validation
# ---------------------------------------------------------------------------

say "Validating candidate release"

as_admin "${BUILD_PYTHON}" - "${RELEASE_DIR}" "${MAIN_SHA}" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
main_sha = sys.argv[2]

required = [
    root / "backend" / "app" / "main.py",
    root / "src" / "site" / "index.html",
    root / "src" / "site" / "data" / "wtk_articles_master.jsonl",
    root / "src" / "site" / "data" / "article-index.jsonl",
    root / "src" / "site" / "data" / "search" / "wanttoknow-search.sqlite",
    root / "src" / "site" / "data" / "search" / "related-content.json",
]

missing = [str(p) for p in required if not p.is_file()]
if missing:
    raise SystemExit("Missing required release files:\n" + "\n".join(missing))

master = root / "src/site/data/wtk_articles_master.jsonl"
index = root / "src/site/data/article-index.jsonl"

articles = []
with master.open(encoding="utf-8") as fh:
    for lineno, line in enumerate(fh, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid canonical JSONL at line {lineno}: {exc}")
        article_id = str(row.get("article_id") or "").strip()
        slug = str(row.get("slug") or "").strip()
        if not article_id or not slug:
            raise SystemExit(f"Canonical article line {lineno} lacks article_id or slug")
        articles.append((article_id, slug))

index_count = sum(1 for line in index.open(encoding="utf-8") if line.strip())
if index_count != len(articles):
    raise SystemExit(
        f"Article index count mismatch: master={len(articles)} index={index_count}"
    )

news = root / "src/site/news"
missing_pages = []
for article_id, slug in articles:
    page = news / f"{slug}.html"
    if not page.is_file() or page.stat().st_size < 500:
        missing_pages.append(f"{article_id}:{slug}")
        if len(missing_pages) >= 20:
            break

if missing_pages:
    raise SystemExit(
        "Generated news pages missing/too small (first matches): "
        + ", ".join(missing_pages)
    )

import sqlite3

search_db = root / "src/site/data/search/wanttoknow-search.sqlite"
con = sqlite3.connect(search_db)
try:
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"Search DB integrity_check failed: {integrity}")

    tables = {
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    required_tables = {
        "ref_registry",
        "content",
        "content_terms",
        "fts_content",
        "related_content",
    }
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        raise SystemExit(
            "Search DB missing required tables: "
            + ", ".join(missing_tables)
        )

    content_count = con.execute(
        "SELECT COUNT(*) FROM content"
    ).fetchone()[0]
    fts_count = con.execute(
        "SELECT COUNT(*) FROM fts_content"
    ).fetchone()[0]

    if content_count < len(articles):
        raise SystemExit(
            f"Search DB content count unexpectedly small: {content_count}"
        )

    if fts_count != content_count:
        raise SystemExit(
            f"Search FTS/content count mismatch: "
            f"fts={fts_count} content={content_count}"
        )
finally:
    con.close()

related_path = root / "src/site/data/search/related-content.json"
related = json.loads(related_path.read_text(encoding="utf-8"))
if not isinstance(related, dict) or not related:
    raise SystemExit("Related-content map is empty or invalid")

bad_related = [
    key
    for key, value in related.items()
    if not isinstance(value, list) or len(value) > 24
]
if bad_related:
    raise SystemExit(
        "Invalid related-content entries (first matches): "
        + ", ".join(map(str, bad_related[:20]))
    )

print(f"PASS canonical_articles={len(articles)}")
print(f"PASS search_content={content_count}")
print(f"PASS related_refs={len(related)}")
print(f"PASS article_index={index_count}")
print(f"PASS origin_main={main_sha}")
PY

# Release metadata is operational, not site source.
python3 - "${RELEASE_DIR}/.wtk-release.json" "${MAIN_SHA}" "${MAIN_SUBJECT}" "${PREVIOUS_TARGET}" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path, sha, subject, previous = sys.argv[1:]
payload = {
    "built_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "main_sha": sha,
    "main_subject": subject,
    "previous_release": previous,
}
Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

chmod -R a+rX "${RELEASE_DIR}"

# ---------------------------------------------------------------------------
# Atomic switch
# ---------------------------------------------------------------------------

say "Testing candidate backend with durable production runtime"

if ! (
    cd "${RELEASE_DIR}/backend"
    sudo -u wtkapp \
        "${RUNTIME_PYTHON}" \
        -c 'import app.main'
); then
    die "Candidate backend cannot import with durable production runtime"
fi

say "Switching current -> ${RELEASE_DIR}"

NEXT_LINK="${CURRENT_LINK}.next.$$"
rm -f "${NEXT_LINK}"
ln -s "${RELEASE_DIR}" "${NEXT_LINK}"
mv -Tf "${NEXT_LINK}" "${CURRENT_LINK}"
SWITCHED=1

say "Restarting ${SERVICE}"
systemctl restart "${SERVICE}"

# Give systemd/FastAPI a short bounded window to come up.
for _ in {1..15}; do
    if systemctl is-active --quiet "${SERVICE}" &&
       curl -fsS --max-time 4 "http://127.0.0.1:8000/api/health" >/dev/null
    then
        break
    fi
    sleep 1
done

systemctl is-active --quiet "${SERVICE}" \
    || die "${SERVICE} did not become active"

curl -fsS --max-time 5 \
    "http://127.0.0.1:8000/api/health" >/dev/null \
    || die "FastAPI health check failed"

curl -fsS --max-time 8 \
    "http://127.0.0.1:8000/api/search/options" >/dev/null \
    || die "Search API smoke test failed"

curl -fsS --max-time 10 \
    --resolve "${PUBLIC_HOST}:443:127.0.0.1" \
    "https://${PUBLIC_HOST}/" >/dev/null \
    || die "HTTPS homepage smoke test failed for ${PUBLIC_HOST}"

SWITCHED=0
trap - EXIT INT TERM

say "DEPLOYED ${MAIN_SHORT}: ${MAIN_SUBJECT}"
say "Current release: $(readlink -f "${CURRENT_LINK}")"
say "Previous release retained: ${PREVIOUS_TARGET}"
say "Build log: ${DEPLOY_LOG}"
