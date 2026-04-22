"""Code Auditor subagent.

Reads files and greps patterns in response to a focused question. Returns a
structured `AuditResult` with file:line citations. No `Bash` / `Edit` / `Write` —
this is read-only.
"""
from __future__ import annotations

import logging
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

from .base import (
    SubagentResult,
    cost_from_result_message,
    duration_from_result_message,
    extract_result_block,
    load_subagent_prompt,
)

log = logging.getLogger(__name__)


async def audit(
    repo_path: Path,
    question: str,
    *,
    hints: list[str] | None = None,
    max_budget_usd: float = 1.00,
    max_turns: int = 6,
) -> SubagentResult:
    """Ask the Code Auditor a focused question about the repo."""
    if not repo_path or not repo_path.exists():
        return SubagentResult(
            ok=False,
            summary="repo_path does not exist",
            error=f"not_found: {repo_path}",
        )
    if not question.strip():
        return SubagentResult(ok=False, summary="empty question", error="empty_input")

    system_prompt = load_subagent_prompt("code_auditor")

    prompt_lines = [f"Question: {question.strip()}"]
    if hints:
        prompt_lines.append("")
        prompt_lines.append("Hints (files or patterns the conductor suggests checking first):")
        for h in hints:
            prompt_lines.append(f"- {h}")
    prompt_lines.append("")
    prompt_lines.append("Run your inspection and emit ONE `## AuditResult:` block per your contract.")
    prompt = "\n".join(prompt_lines)

    options = ClaudeAgentOptions(
        model="claude-opus-4-7",
        system_prompt=system_prompt,
        allowed_tools=["Read", "Grep", "Glob"],
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
    parsed = extract_result_block(full_text, expected_kind="AuditResult")
    if not parsed:
        return SubagentResult(
            ok=False,
            summary="code_auditor did not emit a valid AuditResult block",
            error=f"raw output (first 500 chars): {full_text[:500]}",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    return SubagentResult(
        ok=bool(parsed.get("ok", True)),
        summary=str(parsed.get("summary", "")),
        payload=parsed,
        cost_usd=total_cost,
        duration_ms=duration_ms,
    )
