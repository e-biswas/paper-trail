"""Patch Generator subagent.

Takes a ratified hypothesis + supporting evidence and returns a unified
diff WITHOUT applying it. The conductor runs `git apply --check` before
actually applying the diff, which keeps fix application auditable and
makes retries cheap on a mismatched context.

No `Edit` / `Write` / `Bash` / `Task` — read-only inspection only. See
`docs/backend/subagents.md` for the role + schema.
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
    extract_fenced_diff,
    extract_result_block,
    load_subagent_prompt,
)

log = logging.getLogger(__name__)


async def generate(
    repo_path: Path,
    hypothesis_id: str,
    evidence_summary: str,
    *,
    retry_of: str | None = None,
    max_budget_usd: float = 1.00,
    max_turns: int = 4,
) -> SubagentResult:
    """Ask the Patch Generator to propose a unified diff for `hypothesis_id`.

    `evidence_summary` is the conductor's short description of what was
    observed (e.g. "imputation fit on full df at prepare_data.py:28").
    `retry_of`, when present, is the `git apply --check` error output from
    a previous failed patch — included verbatim so the subagent can fix
    its context lines on the second attempt.
    """
    if not repo_path or not repo_path.exists():
        return SubagentResult(
            ok=False,
            summary="repo_path does not exist",
            error=f"not_found: {repo_path}",
        )
    if not hypothesis_id.strip():
        return SubagentResult(ok=False, summary="empty hypothesis_id", error="empty_input")
    if not evidence_summary.strip():
        return SubagentResult(ok=False, summary="empty evidence_summary", error="empty_input")

    system_prompt = load_subagent_prompt("patch_generator")

    lines = [
        f"hypothesis_id: {hypothesis_id.strip()}",
        "",
        "evidence_summary:",
        evidence_summary.strip(),
        "",
    ]
    if retry_of:
        lines += [
            "RETRY — your previous patch failed `git apply --check` with:",
            "",
            retry_of.strip(),
            "",
            "Read the target files again, correct the mismatched context, and emit a fresh `## Patch:` block.",
            "",
        ]
    else:
        lines.append(
            "Locate the exact code to change, confirm with Read/Grep, "
            "then emit one `## Patch:` block followed by one fenced ```diff``` block "
            "per your operating contract."
        )
    prompt = "\n".join(lines)

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
                    if isinstance(block, TextBlock) and block.text:
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
    parsed = extract_result_block(full_text, expected_kind="Patch")
    if not parsed:
        return SubagentResult(
            ok=False,
            summary="patch_generator did not emit a valid Patch block",
            error=f"raw output (first 600 chars): {full_text[:600]}",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    diff_text = extract_fenced_diff(full_text)
    if not diff_text or not _looks_like_unified_diff(diff_text):
        return SubagentResult(
            ok=False,
            summary="patch_generator emitted a Patch block but no well-formed fenced diff",
            payload={"metadata": parsed, "raw_diff": diff_text or ""},
            error="missing_or_malformed_diff",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    target_files = parsed.get("target_files")
    if isinstance(target_files, str):
        # tolerate "[a, b]" style that slipped through
        target_files = [s.strip() for s in target_files.strip("[]").split(",") if s.strip()]
    if not isinstance(target_files, list):
        target_files = []

    payload: dict[str, Any] = {
        "hypothesis_id": str(parsed.get("hypothesis_id", hypothesis_id)).strip(),
        "rationale": str(parsed.get("rationale", "")).strip(),
        "target_files": [str(p) for p in target_files],
        "notes": str(parsed.get("notes", "")).strip(),
        "diff": diff_text,
    }

    return SubagentResult(
        ok=True,
        summary=payload["rationale"] or "patch generated",
        payload=payload,
        cost_usd=total_cost,
        duration_ms=duration_ms,
    )


def _looks_like_unified_diff(text: str) -> bool:
    """Cheap sanity check that `text` contains a recognisable unified diff."""
    if "\n" not in text:
        return False
    has_old_header = "--- a/" in text or text.startswith("--- ")
    has_new_header = "+++ b/" in text or "\n+++ " in text
    has_hunk = "\n@@ " in text or text.startswith("@@ ")
    return has_old_header and has_new_header and has_hunk
