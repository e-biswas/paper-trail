"""Sandbox interface + MVP backend.

Usage:

    from server.sandbox import LocalSandbox
    sb = LocalSandbox("/tmp/muchlinski-demo")
    result = await sb.exec(["python", "src/eval.py"], timeout_s=120)
"""
from .base import (
    ExecResult,
    PathConfinementError,
    Sandbox,
    SandboxError,
    SandboxExecError,
)
from .local import LocalSandbox

__all__ = [
    "ExecResult",
    "LocalSandbox",
    "PathConfinementError",
    "Sandbox",
    "SandboxError",
    "SandboxExecError",
]
