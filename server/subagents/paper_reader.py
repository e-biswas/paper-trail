"""Paper Reader subagent.

Tool-free. Input: the full markdown of a Paper object's `full_markdown` field
(or a pre-distilled claim summary like `test_data/papers/muchlinski.md`).
Output: a structured `PaperSummary` extracting primary_claim, dataset,
metric, reported_value, and methodological commitments.

Useful first subagent to implement because it has zero tool surface —
the only integration risk is SDK streaming.
"""
from __future__ import annotations

import logging
import time
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


async def summarize(paper_markdown: str, *, max_budget_usd: float = 0.50) -> SubagentResult:
    """Read a paper's markdown and return a PaperSummary."""
    if not paper_markdown or len(paper_markdown.strip()) < 20:
        return SubagentResult(
            ok=False,
            summary="paper markdown is empty or too short",
            error="empty_input",
        )

    system_prompt = load_subagent_prompt("paper_reader")

    # Truncate very long inputs (>40K chars) with a clear marker — protects
    # token budget without silently lying about what the subagent saw.
    MAX_CHARS = 40_000
    body = paper_markdown
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + f"\n\n[... truncated; original was {len(paper_markdown)} chars ...]"

    options = ClaudeAgentOptions(
        model="claude-opus-4-7",
        system_prompt=system_prompt,
        allowed_tools=[],
        max_turns=2,
        max_budget_usd=max_budget_usd,
        include_partial_messages=False,
    )

    prompt = (
        "Paper text follows. Extract the reproducibility-relevant claims per "
        "your operating contract, then emit one `## PaperSummary:` block.\n\n"
        "------------------\n"
        f"{body}\n"
        "------------------"
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
    result = extract_result_block(full_text, expected_kind="PaperSummary")
    if not result:
        return SubagentResult(
            ok=False,
            summary="paper_reader did not emit a valid PaperSummary block",
            error=f"raw output (first 500 chars): {full_text[:500]}",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    return SubagentResult(
        ok=bool(result.get("ok", True)),
        summary=str(result.get("primary_claim", "")),
        payload=result,
        cost_usd=total_cost,
        duration_ms=duration_ms,
    )
