"""`LocalSandbox` — the only MVP sandbox backend.

Executes commands inside a pre-staged `/tmp/<fixture>-demo/` directory. Not a
security sandbox — arbitrary subprocesses can still open network connections
or write outside the workdir — but it enforces the controls the project cares
most about:

    - Path confinement on `read_text` / `write_text`.
    - Hard wall-clock timeout with guaranteed process kill.
    - Output cap so a runaway process can't fill memory.
    - Env scrubbing (no inherited `PYTHONPATH` / `VIRTUAL_ENV` / etc.).
    - No `shell=True` — commands are always lists.

These are documented caveats (see `docs/backend/sandbox.md`). The seam exists
so a future `E2BSandbox` can tighten these without rewriting callers.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import signal
import time
from pathlib import Path
from typing import Any

from .base import ExecResult, PathConfinementError, Sandbox, SandboxError, SandboxExecError

log = logging.getLogger(__name__)


# Minimum environment the sandboxed process sees. Anything else must be
# explicitly passed via the `env` kwarg.
_SAFE_BASE_ENV_KEYS: tuple[str, ...] = ("PATH", "HOME", "LANG", "LC_ALL", "TERM", "TZ")

# Paths we refuse to use as a workdir — protects against accidentally running
# the sandbox at a sensitive location.
_FORBIDDEN_WORKDIRS: tuple[Path, ...] = tuple(
    Path(p) for p in ("/", "/etc", "/usr", "/bin", "/sbin", "/var", "/boot", "/root", "/home")
)


class LocalSandbox:
    """Filesystem-local sandbox with path and resource guardrails."""

    def __init__(self, workdir: Path | str) -> None:
        wd = Path(workdir).expanduser().resolve()
        if not wd.exists() or not wd.is_dir():
            raise SandboxError(f"workdir does not exist or is not a directory: {wd}")

        # Don't allow anyone to pass a root-like path. Compare against resolved
        # canonical form.
        if any(wd == forbid or wd == forbid.resolve() for forbid in _FORBIDDEN_WORKDIRS):
            raise SandboxError(f"refusing to use system path as workdir: {wd}")
        # Also refuse $HOME itself (but subdirs are fine).
        home = Path(os.path.expanduser("~")).resolve()
        if wd == home:
            raise SandboxError(f"refusing to use $HOME as workdir: {wd}")

        self._workdir = wd
        log.debug("LocalSandbox initialized at %s", self._workdir)

    # ------------------------------------------------------------------ #
    # Protocol surface
    # ------------------------------------------------------------------ #

    @property
    def workdir(self) -> Path:
        return self._workdir

    async def exec(
        self,
        command: str | list[str],
        *,
        timeout_s: float = 120.0,
        env: dict[str, str] | None = None,
        stdout_cap_bytes: int = 512_000,
    ) -> ExecResult:
        """Run `command` in `self.workdir`. Never `shell=True`."""
        argv = _normalize_argv(command)
        if not argv:
            raise SandboxExecError("empty command")

        effective_env = _build_env(env)
        redacted = _redact(argv)
        log.info("sandbox exec: %s (workdir=%s)", redacted, self._workdir)

        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self._workdir),
            env=effective_env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # New process group so we can kill descendants on timeout.
            start_new_session=True,
        )

        stdout_task = asyncio.create_task(_read_capped(proc.stdout, stdout_cap_bytes))
        stderr_task = asyncio.create_task(_read_capped(proc.stderr, stdout_cap_bytes))

        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=timeout_s)
        except asyncio.TimeoutError:
            timed_out = True
            _kill_process_group(proc)
            # Give it a moment to actually exit after SIGKILL.
            try:
                await asyncio.wait_for(proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:  # pragma: no cover — extremely unlikely
                log.warning("process %d failed to die after SIGKILL", proc.pid)

        stdout_bytes, stdout_truncated = await stdout_task
        stderr_bytes, stderr_truncated = await stderr_task

        duration_ms = int((time.monotonic() - started) * 1000)
        returncode = proc.returncode if proc.returncode is not None else -1
        ok = (returncode == 0) and not timed_out

        return ExecResult(
            ok=ok,
            returncode=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_ms=duration_ms,
            truncated=stdout_truncated or stderr_truncated,
            timed_out=timed_out,
            command=argv,
            workdir=self._workdir,
        )

    async def read_text(self, rel_path: str) -> str:
        target = self._confine(rel_path)
        return await asyncio.to_thread(target.read_text, encoding="utf-8")

    async def write_text(self, rel_path: str, content: str) -> None:
        target = self._confine(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, content, encoding="utf-8")

    async def close(self) -> None:
        """No-op for LocalSandbox. Protocol compatibility only."""
        return None

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #

    def _confine(self, rel_path: str) -> Path:
        """Resolve `rel_path` against `workdir`, refusing any path that
        escapes (symlinks included)."""
        if not isinstance(rel_path, str) or not rel_path:
            raise PathConfinementError("rel_path must be a non-empty string")
        if Path(rel_path).is_absolute():
            raise PathConfinementError(f"absolute path not allowed: {rel_path}")
        candidate = (self._workdir / rel_path).resolve()
        if candidate != self._workdir and self._workdir not in candidate.parents:
            raise PathConfinementError(
                f"path {rel_path!r} escapes workdir {self._workdir}"
            )
        return candidate


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _normalize_argv(command: str | list[str]) -> list[str]:
    if isinstance(command, list):
        return [str(part) for part in command]
    if not isinstance(command, str):
        raise SandboxExecError(f"command must be str or list[str], got {type(command)!r}")
    # Deliberately no shell — split with shlex. Users who want shell features
    # can pass `["sh", "-c", "cmd1 | cmd2"]` explicitly.
    return shlex.split(command)


def _build_env(user_env: dict[str, str] | None) -> dict[str, str]:
    base: dict[str, str] = {}
    for key in _SAFE_BASE_ENV_KEYS:
        value = os.environ.get(key)
        if value is not None:
            base[key] = value
    if user_env:
        base.update(user_env)
    return base


async def _read_capped(stream: asyncio.StreamReader | None, cap: int) -> tuple[bytes, bool]:
    """Read up to `cap` bytes from the stream. Return (data, truncated)."""
    if stream is None:
        return b"", False
    chunks: list[bytes] = []
    total = 0
    truncated = False
    while total < cap:
        chunk = await stream.read(min(64 * 1024, cap - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
    if stream.at_eof():
        return b"".join(chunks), False
    # Drain the rest so the subprocess can exit; discard it.
    while True:
        remaining = await stream.read(64 * 1024)
        if not remaining:
            break
        truncated = True
    return b"".join(chunks), truncated


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Best-effort SIGKILL on the process group we started. Silently tolerate
    races where the process already exited.
    """
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


_REDACT_KEYWORDS = ("password", "token", "secret", "api_key", "pat")


def _redact(argv: list[str]) -> str:
    redacted: list[str] = []
    for part in argv:
        low = part.lower()
        if any(k in low for k in _REDACT_KEYWORDS) and "=" in part:
            key, _, _ = part.partition("=")
            redacted.append(f"{key}=***")
        else:
            redacted.append(part)
    return shlex.join(redacted)
