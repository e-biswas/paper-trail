"""Experiment Runner subagent.

Executes ONE bash command inside the repo's sandboxed working directory and
returns a structured `RunResult` (including a parsed `METRIC_JSON:` line if
present in stdout).

The SDK's `Bash` tool runs with `cwd=repo_path`, giving us filesystem
confinement at the process level. For MVP we accept the SDK's `Bash` behavior
rather than routing through the custom `Sandbox.exec()` wrapper — documented
in `docs/backend/sandbox.md`.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)


def _venv_python() -> Path | None:
    """Path to the project's `.venv/bin/python`, or None if the venv is absent."""
    project_root = Path(__file__).resolve().parent.parent.parent
    candidate = project_root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def _rewrite_command_to_venv_python(command: str) -> str:
    """If the command starts with bare `python` or `python3`, rewrite it to
    the project's venv python so sklearn/pandas/numpy are available.
    Idempotent — does nothing if the command already uses an absolute path.
    """
    venv = _venv_python()
    if venv is None:
        return command
    stripped = command.lstrip()
    for prefix in ("python3 ", "python "):
        if stripped.startswith(prefix):
            return f"{venv} {stripped[len(prefix):]}"
    return command

from .base import (
    SubagentResult,
    cost_from_result_message,
    duration_from_result_message,
    extract_result_block,
    load_subagent_prompt,
)

log = logging.getLogger(__name__)


async def run(
    repo_path: Path,
    command: str,
    *,
    max_budget_usd: float = 1.00,
    max_turns: int = 4,
) -> SubagentResult:
    """Ask the Experiment Runner to execute `command` in `repo_path` and parse stdout."""
    if not repo_path or not repo_path.exists():
        return SubagentResult(
            ok=False,
            summary="repo_path does not exist",
            error=f"not_found: {repo_path}",
        )
    if not command.strip():
        return SubagentResult(ok=False, summary="empty command", error="empty_input")

    system_prompt = load_subagent_prompt("experiment_runner")

    # Rewrite `python` → the project's venv python so sklearn is on import path.
    effective_command = _rewrite_command_to_venv_python(command)

    prompt = (
        f"Run this command inside the repo and report the result per your contract:\n\n"
        f"    {effective_command}\n\n"
        "Emit one `## RunResult:` block. Do not run additional commands unless "
        "the one I asked fails and a single follow-up is needed."
    )

    options = ClaudeAgentOptions(
        model="claude-opus-4-7",
        system_prompt=system_prompt,
        allowed_tools=["Bash"],
        cwd=str(repo_path),
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        include_partial_messages=False,
    )

    collected_text: list[str] = []
    total_cost = 0.0
    duration_ms = 0
    started = time.monotonic()

    try:
        async for msg in query(prompt=prompt, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        collected_text.append(block.text)
            elif isinstance(msg, ResultMessage):
                total_cost = cost_from_result_message(msg)
                duration_ms = duration_from_result_message(msg)
                if getattr(msg, "is_error", False):
                    return SubagentResult(
                        ok=False,
                        summary="SDK returned is_error=True",
                        error=str(getattr(msg, "result", "unknown")),
                        cost_usd=total_cost,
                        duration_ms=duration_ms,
                    )
                break
    except Exception as exc:
        return SubagentResult(
            ok=False,
            summary=f"SDK error: {type(exc).__name__}",
            error=str(exc),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    full_text = "\n".join(collected_text)
    parsed = extract_result_block(full_text, expected_kind="RunResult")
    if not parsed:
        return SubagentResult(
            ok=False,
            summary="experiment_runner did not emit a valid RunResult block",
            error=f"raw output (first 500 chars): {full_text[:500]}",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    return SubagentResult(
        ok=bool(parsed.get("ok", False)),
        summary=str(parsed.get("summary", "")),
        payload=parsed,
        cost_usd=total_cost,
        duration_ms=duration_ms,
    )
