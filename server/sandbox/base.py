"""Sandbox interface + shared types.

The `Sandbox` protocol is the seam every code-execution call in this project
passes through. MVP ships `LocalSandbox` (see `local.py`) as the only backend.
A future `E2BSandbox` or `DockerSandbox` can be dropped in without touching
subagents, as long as it fulfils this protocol.

Why a Protocol rather than an abstract base class:
    structural typing lets tests pass in lightweight fakes without inheritance,
    and keeps the concrete backends independent of each other.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class SandboxError(RuntimeError):
    """Base class for sandbox-level errors."""


class PathConfinementError(SandboxError):
    """Raised when a `read_text`/`write_text` call attempts to escape the
    sandbox's working directory.
    """


class SandboxExecError(SandboxError):
    """Raised when a subprocess could not be spawned or collected."""


@dataclass(frozen=True)
class ExecResult:
    """Result of running a command inside a sandbox.

    - `ok` is True iff the process returned 0 AND did not time out.
    - `stdout` / `stderr` are decoded UTF-8 with `errors="replace"` and may be
      truncated to the caller-specified cap (see `truncated`).
    - `duration_ms` is the wall-clock runtime including spawn overhead.
    """

    ok: bool
    returncode: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool
    timed_out: bool
    command: list[str]
    workdir: Path

    def as_envelope_data(self) -> dict[str, Any]:
        """Shape suited for embedding inside a `tool_result` envelope."""
        return {
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "truncated": self.truncated,
            "timed_out": self.timed_out,
        }


@runtime_checkable
class Sandbox(Protocol):
    """The narrow protocol every sandbox backend must implement."""

    @property
    def workdir(self) -> Path: ...

    async def exec(
        self,
        command: str | list[str],
        *,
        timeout_s: float = 120.0,
        env: dict[str, str] | None = None,
        stdout_cap_bytes: int = 512_000,
    ) -> ExecResult: ...

    async def read_text(self, rel_path: str) -> str: ...

    async def write_text(self, rel_path: str, content: str) -> None: ...

    async def close(self) -> None: ...
