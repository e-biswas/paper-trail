"""Environment loading and validation.

Loads `.env` from the repo root into `os.environ` (if not already set by the
caller) and validates that required keys are present. Any missing required key
raises `EnvError` at startup — fail-fast is better than a mysterious runtime
failure several turns into an agent loop.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class EnvError(RuntimeError):
    """Raised when required environment variables are missing or malformed."""


REQUIRED_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
)

# GitHub credentials are required only when the conductor is allowed to open
# real PRs. Day 1 runs work without them; we load and warn rather than raise.
GITHUB_KEYS: tuple[str, ...] = (
    "GITHUB_TOKEN",
    "GITHUB_BOT_OWNER",
    "GITHUB_BOT_REPO",
)

_DEFAULT_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(env_file: Path | None = None) -> None:
    """Parse `.env` (if present) into os.environ without clobbering existing values.

    Called once from FastAPI's startup hook. Safe to call multiple times.
    """
    target = env_file or _DEFAULT_ENV_FILE
    if target.exists():
        _parse_env_file(target)
    else:
        log.debug("no .env file found at %s; relying on ambient environment", target)

    missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        raise EnvError(
            f"Missing required environment variables: {missing}. "
            f"Copy .env.example to .env and fill them in."
        )

    missing_github = [k for k in GITHUB_KEYS if not os.environ.get(k)]
    if missing_github:
        log.warning(
            "GitHub credentials not set (%s). PR creation will be disabled. "
            "Set these in .env before recording the demo video.",
            ", ".join(missing_github),
        )


def _parse_env_file(path: Path) -> None:
    """Minimal `.env` parser. No quoting, no substitution, no multi-line."""
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            log.warning("%s:%d: skipping malformed line", path, lineno)
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Don't override values already in the environment (lets CI / systemd win).
        os.environ.setdefault(key, value)
