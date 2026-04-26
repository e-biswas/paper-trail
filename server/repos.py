"""Repo attach helper — one input, one resolved repo.

Accepts either:
  - a GitHub URL (https://github.com/owner/repo[.git][/tree/branch])
  - a bare slug (owner/repo)
  - a local filesystem path to an existing directory

Returns a resolved `ResolvedRepo` the orchestrator can hand to `RunConfig`.
Remote repos are cloned under `~/.cache/paper-trail/repos/` on first use and
reused thereafter; we deliberately skip `git pull` so a live demo run is never
at the mercy of an upstream force-push.

Branch handling:
- `/tree/<branch>` is parsed out of GitHub URLs so the user can attach a
  non-default branch by pasting its URL directly. `<branch>` may contain
  slashes (e.g. `eb/video-materials`).
- The cache directory is keyed per-branch. Different branches of the same
  repo never share a working tree, so an agent run on branch A can never
  silently inherit state (HEAD position, edits, new commits) from a prior
  run on branch B.
- On cache hit we validate the checkout: HEAD must match the requested
  branch and the working tree must be clean. If either check fails we wipe
  and reclone, surfacing a `warning` so the user knows the cache was reset.

Design:
- Subprocess-driven `git`. No gitpython dependency (one less thing to fail).
- Shallow clones (`--depth=1 --single-branch`) keep disk + time small.
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
    default_branch: str | None        # branch the local checkout currently points at
    source: str                       # "clone" | "cache" | "local"
    already_cloned: bool
    requested_branch: str | None = None  # branch parsed from the URL, if any
    warning: str | None = None


# ----- URL / slug parsing ------------------------------------------------


# Accepts: https://github.com/owner/repo(.git)?(/tree/<branch>)?(?...|#...)?  or  owner/repo
#
# The branch capture is *greedy* and stops only at `?` / `#` / whitespace,
# so URLs with slash-bearing branches like `/tree/eb/video-materials` are
# captured intact. This sacrifices the rare GitHub URL form
# `/tree/<branch>/<subdir>` (a folder listing on a branch): we read the whole
# tail as the branch name. When that's wrong, `git clone --branch ...` fails
# loudly so the user knows to re-paste without the path component.
_GITHUB_URL_RE = re.compile(
    r"^https?://(?:www\.)?github\.com/(?P<owner>[^/\s]+)/(?P<repo>[^/\s#?]+?)(?:\.git)?"
    r"(?:/tree/(?P<branch>[^\s?#]+))?"
    r"(?:[/?#].*)?$",
    re.IGNORECASE,
)
_SLUG_RE = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?$")


def parse_github_handle(s: str) -> tuple[str, str, str | None] | None:
    """Return (owner, repo, branch_or_None) for any GitHub URL or slug; None otherwise.

    Branch is parsed from `/tree/<branch>` URLs and may contain slashes.
    Bare slugs (`owner/repo`) carry no branch info.
    """
    s = s.strip()
    if not s:
        return None
    m = _GITHUB_URL_RE.match(s)
    if m:
        branch = m.group("branch")
        # Strip any stray trailing slash from the branch capture.
        if branch:
            branch = branch.rstrip("/")
        return m.group("owner"), m.group("repo"), branch or None
    # Plain slug like "owner/repo" — disambiguate from a local path.
    if s.startswith(("/", ".", "~")) or "\\" in s:
        return None
    m = _SLUG_RE.match(s)
    if m:
        return m.group("owner"), m.group("repo"), None
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
        owner, repo, branch = handle
        slug = f"{owner}/{repo}"
        return _ensure_clone(slug, branch, cache_root)

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


def _safe_branch_segment(branch: str) -> str:
    """Convert a branch name into a filesystem-safe directory segment.

    `eb/video-materials` → `eb--video-materials`. Anything outside the safe
    set becomes `_` so we can't accidentally escape the cache root.
    """
    return re.sub(r"[^A-Za-z0-9._-]", "_", branch.replace("/", "--"))


def _cache_dest(cache_root: Path, slug: str, branch: str | None) -> Path:
    """Per-(slug, branch) cache directory.

    Branch-blind keys are still used when no branch was requested. This keeps
    the existing demo cache directories valid: `owner__repo` continues to
    mean "default branch HEAD."
    """
    owner, repo = slug.split("/", 1)
    if branch:
        return cache_root / f"{owner}__{repo}__{_safe_branch_segment(branch)}"
    return cache_root / f"{owner}__{repo}"


def _ensure_clone(slug: str, branch: str | None, cache_root: Path) -> ResolvedRepo:
    cache_root.mkdir(parents=True, exist_ok=True)
    dest = _cache_dest(cache_root, slug, branch)

    reset_warning: str | None = None

    if dest.exists() and (dest / ".git").exists():
        ok, reason = _validate_cache(dest, branch)
        if ok:
            return ResolvedRepo(
                local_path=dest.resolve(),
                slug=slug,
                default_branch=_default_branch_local(dest),
                source="cache",
                already_cloned=True,
                requested_branch=branch,
            )
        # Cache is unusable — wipe and reclone, but tell the user why.
        log.warning("cache reset for %s (%s): %s", slug, branch or "default", reason)
        shutil.rmtree(dest, ignore_errors=True)
        reset_warning = (
            f"cached checkout was reset before this run ({reason}). "
            "If a previous run left edits behind, they're gone now."
        )
    elif dest.exists():
        # Stale half-clone (no .git). Wipe.
        shutil.rmtree(dest, ignore_errors=True)

    url = f"https://github.com/{slug}.git"
    cmd = ["git", "clone", "--depth=1", "--single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(dest)]

    log.info("cloning %s%s → %s", url, f" @ {branch}" if branch else "", dest)
    try:
        proc = subprocess.run(
            cmd,
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
        if branch:
            raise RepoAttachError(
                f"git clone failed for {slug}@{branch}: {msg}. "
                "Check that the branch exists on the remote."
            )
        raise RepoAttachError(f"git clone failed for {slug}: {msg}")

    # Cheap size guard (post-clone) so pathological repos don't sit in the
    # cache forever. Shallow clones usually stay small, but better safe.
    size_mb = _dir_size_mb(dest)
    warning_parts: list[str] = []
    if reset_warning:
        warning_parts.append(reset_warning)
    if size_mb > _MAX_REPO_SIZE_MB:
        warning_parts.append(
            f"repo is large ({size_mb:.0f} MB); agent reads may be slow. "
            "Consider using a smaller fork for the demo."
        )
    warning = " · ".join(warning_parts) if warning_parts else None

    return ResolvedRepo(
        local_path=dest.resolve(),
        slug=slug,
        default_branch=_default_branch_local(dest),
        source="clone",
        already_cloned=False,
        requested_branch=branch,
        warning=warning,
    )


def _validate_cache(dest: Path, requested_branch: str | None) -> tuple[bool, str]:
    """Return (ok, reason). Reason is empty when ok=True.

    Two failure modes we care about:
      1. HEAD is on a different branch than the user asked for. This is a
         silent-correctness footgun — the agent would read the wrong code.
      2. Working tree is dirty (edits, untracked files, or new commits beyond
         the original shallow tip). A previous run may have left state we
         shouldn't inherit.
    """
    head = _default_branch_local(dest)
    if requested_branch and head != requested_branch:
        return False, f"HEAD is on '{head}', expected '{requested_branch}'"

    try:
        proc = subprocess.run(
            ["git", "-C", str(dest), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False, "could not run `git status` to verify cache cleanliness"
    if proc.returncode != 0:
        return False, "`git status` failed"
    if proc.stdout.strip():
        return False, "working tree has uncommitted edits or untracked files"
    return True, ""


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
    owner, repo, _branch = handle
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
