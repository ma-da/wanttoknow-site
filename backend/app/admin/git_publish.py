from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


class GitPublishError(RuntimeError):
    pass


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "Git command failed").strip()
        raise GitPublishError(detail[:4000])
    return proc


def _rev(root: Path, ref: str) -> str:
    return _git(root, "rev-parse", ref).stdout.strip()


def ensure_dev_checkpoint(root: Path, *, branch: str = "dev") -> str:
    """Require a clean dev worktree exactly synchronized with origin/dev.

    The no-op push is intentional: publication will not start unless the remote
    is reachable and the known-good local commit is already safely present on
    the remote dev branch.
    """
    inside = _git(root, "rev-parse", "--is-inside-work-tree", check=False)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        raise GitPublishError(f"Publication root is not a Git worktree: {root}")

    current_branch = _git(root, "branch", "--show-current").stdout.strip()
    if current_branch != branch:
        raise GitPublishError(
            f"Production admin must publish from Git branch {branch!r}; current branch is {current_branch!r}"
        )

    status = _git(root, "status", "--porcelain=v1", "--untracked-files=all").stdout
    if status.strip():
        sample = "\n".join(status.splitlines()[:12])
        raise GitPublishError(
            "Production admin Git worktree has unexpected source changes. "
            "Commit/push or discard them before publishing.\n" + sample
        )

    _git(root, "fetch", "--quiet", "origin", branch)
    local_sha = _rev(root, "HEAD")
    remote_sha = _rev(root, f"origin/{branch}")
    if local_sha != remote_sha:
        raise GitPublishError(
            f"Production admin is not synchronized with origin/{branch}. "
            f"local={local_sha[:12]} remote={remote_sha[:12]}. "
            "Synchronize/restart the admin before publishing."
        )

    # Fail before building if GitHub/authentication/network is unavailable.
    _git(root, "push", "--porcelain", "origin", f"HEAD:refs/heads/{branch}")
    return local_sha


def append_publish_event(root: Path, event: dict[str, Any]) -> Path:
    """Append a small public-safe audit record used to authorize media versions.

    Internal removal reasons and authentication information must never be put
    here; those remain in SQLite under backend/var.
    """
    path = root / "src/site/data/admin-publish-events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return path


def commit_and_push_dev(
    root: Path,
    *,
    base_sha: str,
    message: str,
    branch: str = "dev",
) -> str:
    """Commit only publisher-managed tracked paths and push them to dev."""
    if _rev(root, "HEAD") != base_sha:
        raise GitPublishError("Git HEAD changed while publication was building; publication aborted")

    # Deliberately narrow staging scope. Generated news and large media are
    # ignored; code or unrelated files can never be swept into an article publish.
    _git(root, "add", "-A", "--", "src/site/data", "src/site/topics")

    staged = _git(root, "diff", "--cached", "--name-only").stdout.splitlines()
    if not staged:
        raise GitPublishError(
            "Publication produced no tracked Git change. "
            "The publication audit file should make every publication traceable."
        )
    for name in staged:
        if not (name.startswith("src/site/data/") or name.startswith("src/site/topics/")):
            raise GitPublishError(f"Unexpected path staged by article publication: {name}")

    _git(root, "commit", "--no-gpg-sign", "-m", message)
    commit_sha = _rev(root, "HEAD")
    try:
        _git(root, "push", "--porcelain", "origin", f"HEAD:refs/heads/{branch}")
    except Exception:
        # Remote was not changed if normal Git push failed. Restore tracked
        # source to the known-good pre-publish commit; caller restores ignored
        # generated/media files using its existing rollback journal.
        _git(root, "reset", "--hard", base_sha, check=False)
        raise
    return commit_sha


def reset_to_checkpoint(root: Path, checkpoint_sha: str) -> None:
    _git(root, "reset", "--hard", checkpoint_sha)


def revert_pushed_commit(root: Path, commit_sha: str, *, branch: str = "dev") -> str:
    """Create and push a normal revert; never rewrite remote dev history."""
    _git(root, "revert", "--no-edit", commit_sha)
    revert_sha = _rev(root, "HEAD")
    _git(root, "push", "--porcelain", "origin", f"HEAD:refs/heads/{branch}")
    return revert_sha
