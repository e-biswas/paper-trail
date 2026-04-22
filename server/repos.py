"""Repo attach helper — one input, one resolved repo.

Accepts either:
  - a GitHub URL (https://github.com/owner/repo[.git][/tree/branch])
  - a bare slug (owner/repo)
  - a local filesystem path to an existing directory

Returns a resolved pair `(local_path, slug)` the orchestrator can hand to
`RunConfig`. Remote repos are cloned under `~/.cache/paper-trail/repos/`
on first use and reused thereafter; we deliberately skip `git pull` so a live
demo run is never at the mercy of an upstream force-push.

Design:
- Subprocess-driven `git`. No gitpython dependency (one less thing to fail).
- Shallow clones (`--depth=1`) keep disk + time small for most ML repos.
- Timeout + size guard so a pathological repo can't hang the server.
- Slug inferred from remote origin when the caller provides a local path
  that is itself a git repo.
- Best-effort: on clone failure the function raises `RepoAttachError` with a
  human message; the endpoint relays that to the UI.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


DEFAULT_CACHE_ROOT = Path(
    os.environ.get(
        "REPRO_REPO_CACHE",
        str(Path.home() / ".cache" / "paper-trail" / "repos"),
    )
)
_CLONE_TIMEOUT_SEC = 90
_MAX_REPO_SIZE_MB = 300


class RepoAttachError(RuntimeError):
    """User-visible failure from `resolve_repo`."""


@dataclass
class ResolvedRepo:
    local_path: Path
    slug: str | None
    default_branch: str | None
    source: str              # "clone" | "cache" | "local"
    already_cloned: bool
    warning: str | None = None


# ----- URL / slug parsing ------------------------------------------------


# Accepts: https://github.com/owner/repo(.git)?/?... or owner/repo
_GITHUB_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+?)(?:\.git)?(?:/.*)?$",
    re.IGNORECASE,
)
_SLUG_RE = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?$")


def parse_github_handle(s: str) -> tuple[str, str] | None:
    """Return (owner, repo) for any GitHub URL or slug; None otherwise."""
    s = s.strip()
    if not s:
        return None
    m = _GITHUB_URL_RE.match(s)
    if m:
        return m.group("owner"), m.group("repo")
    # Plain slug like "owner/repo" — disambiguate from a local path.
    if s.startswith(("/", ".", "~")) or "\\" in s:
        return None
    m = _SLUG_RE.match(s)
    if m:
        return m.group("owner"), m.group("repo")
    return None


# ----- Resolve ---------------------------------------------------------


def resolve_repo(
    input_str: str,
    *,
    cache_root: Path | None = None,
) -> ResolvedRepo:
    """Turn user input into a usable local path + slug.

    Order of attempts:
      1. If it parses as a GitHub URL/slug → clone (or reuse cache).
      2. Else if it's an existing local directory → use as-is; if it's a
         git repo, derive slug from `origin`.
      3. Else raise.
    """
    if not input_str or not input_str.strip():
        raise RepoAttachError("repo input is empty")

    raw = input_str.strip()
    cache_root = cache_root or DEFAULT_CACHE_ROOT

    handle = parse_github_handle(raw)
    if handle:
        owner, repo = handle
        slug = f"{owner}/{repo}"
        return _ensure_clone(slug, cache_root)

    # Local path
    path = Path(os.path.expanduser(raw))
    if path.exists() and path.is_dir():
        slug = _slug_from_local_git(path)
        return ResolvedRepo(
            local_path=path.resolve(),
            slug=slug,
            default_branch=_default_branch_local(path),
            source="local",
            already_cloned=True,
        )

    raise RepoAttachError(
        f"{raw!r} is neither a github URL/slug nor an existing local directory"
    )


def _ensure_clone(slug: str, cache_root: Path) -> ResolvedRepo:
    cache_root.mkdir(parents=True, exist_ok=True)
    owner, repo = slug.split("/", 1)
    dest = cache_root / f"{owner}__{repo}"

    if dest.exists() and (dest / ".git").exists():
        default_branch = _default_branch_local(dest)
        return ResolvedRepo(
            local_path=dest.resolve(),
            slug=slug,
            default_branch=default_branch,
            source="cache",
            already_cloned=True,
        )

    # Clean stale half-clone if any.
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    url = f"https://github.com/{slug}.git"
    log.info("cloning %s → %s", url, dest)
    try:
        proc = subprocess.run(
            ["git", "clone", "--depth=1", "--single-branch", url, str(dest)],
            capture_output=True,
            text=True,
            timeout=_CLONE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise RepoAttachError(
            f"git clone timed out after {_CLONE_TIMEOUT_SEC}s for {slug}"
        ) from exc
    except FileNotFoundError as exc:
        raise RepoAttachError("git is not installed on the server") from exc

    if proc.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        stderr = (proc.stderr or "").strip().splitlines()[-3:]
        msg = "; ".join(stderr) or "unknown git error"
        raise RepoAttachError(f"git clone failed for {slug}: {msg}")

    # Cheap size guard (post-clone) so pathological repos don't sit in the
    # cache forever. Shallow clones usually stay small, but better safe.
    size_mb = _dir_size_mb(dest)
    warning: str | None = None
    if size_mb > _MAX_REPO_SIZE_MB:
        warning = (
            f"repo is large ({size_mb:.0f} MB); agent reads may be slow. "
            "Consider using a smaller fork for the demo."
        )

    return ResolvedRepo(
        local_path=dest.resolve(),
        slug=slug,
        default_branch=_default_branch_local(dest),
        source="clone",
        already_cloned=False,
        warning=warning,
    )


# ----- small helpers ---------------------------------------------------


def _slug_from_local_git(path: Path) -> str | None:
    git_dir = path / ".git"
    if not git_dir.exists():
        return None
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    url = (proc.stdout or "").strip()
    handle = parse_github_handle(url)
    if not handle:
        return None
    owner, repo = handle
    return f"{owner}/{repo}"


def _default_branch_local(path: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if proc.returncode != 0:
        return None
    branch = (proc.stdout or "").strip()
    return branch or None


def _dir_size_mb(path: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            try:
                total += fp.stat().st_size
            except OSError:
                continue
    return total / (1024 * 1024)
