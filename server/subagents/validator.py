"""Validator subagent.

Audits a completed Deep Investigation's output — evidence quality, fix
minimality, causal link between root cause and metric delta, honesty of
the 'Remaining uncertainty' section, plausible follow-ups. Returns a
structured `ValidityReport` the UI renders as a reviewer-style summary
at the bottom of the assistant's reply.

No tools. The validator reads the investigator's already-emitted markdown
and the persisted diff; it does not re-investigate the repo. That discipline
keeps the cost low (~$0.20-0.40) and keeps the review focused on whether
the investigator's reasoning holds up, not whether a fresh investigation
would produce the same answer.
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


# Valid labels / marks / overall values — used for defensive parsing.
VALID_LABELS: tuple[str, ...] = (
    "hypothesis_coverage",
    "evidence_quality",
    "fix_minimality",
    "causal_link",
    "alternative_explanations",
    "uncertainty_honesty",
    "suggested_followup",
)
VALID_MARKS: tuple[str, ...] = ("pass", "warn", "fail")
VALID_OVERALL: tuple[str, ...] = ("strong", "acceptable", "weak", "unreliable")


async def validate(
    *,
    paper_context: str,
    run_transcript: str,
    run_config_summary: str,
    diff_text: str | None = None,
    max_budget_usd: float = 0.60,
    max_turns: int = 3,
) -> SubagentResult:
    """Run the validator on a completed run's artifacts.

    Inputs are all strings; the caller assembles them from the persisted
    RunMeta + event log before calling.
    """
    if not run_transcript or len(run_transcript.strip()) < 100:
        return SubagentResult(
            ok=False,
            summary="transcript is empty or too short to audit",
            error="empty_input",
        )

    system_prompt = load_subagent_prompt("validator")

    # Keep the input compact. Paper context is usually the biggest piece.
    MAX_PAPER = 15_000
    if len(paper_context) > MAX_PAPER:
        paper_context = (
            paper_context[:MAX_PAPER]
            + f"\n\n[... truncated for audit; full paper is {len(paper_context)} chars ...]"
        )

    MAX_TRANSCRIPT = 25_000
    if len(run_transcript) > MAX_TRANSCRIPT:
        # Prefer the tail (which holds the dossier + verdict) over the head.
        run_transcript = (
            f"[... transcript truncated; first {len(run_transcript) - MAX_TRANSCRIPT} chars elided ...]\n\n"
            + run_transcript[-MAX_TRANSCRIPT:]
        )

    prompt_parts = [
        "=== Paper context ===",
        paper_context or "(no paper provided)",
        "",
        "=== Run configuration ===",
        run_config_summary,
        "",
        "=== Investigator transcript ===",
        run_transcript,
    ]
    if diff_text:
        # Cap the diff so we don't blow the context window on a huge PR.
        MAX_DIFF = 8_000
        if len(diff_text) > MAX_DIFF:
            diff_text = diff_text[:MAX_DIFF] + "\n[... diff truncated ...]"
        prompt_parts += ["", "=== Unified diff of the investigator's fix ===", diff_text]

    prompt_parts += [
        "",
        "Audit the investigator's work per your operating contract. "
        "Emit ONE `## ValidityReport:` block. Nothing else.",
    ]
    prompt = "\n".join(prompt_parts)

    options = ClaudeAgentOptions(
        model="claude-opus-4-7",
        system_prompt=system_prompt,
        allowed_tools=[],
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
    parsed = extract_result_block(full_text, expected_kind="ValidityReport")
    if not parsed:
        return SubagentResult(
            ok=False,
            summary="validator did not emit a valid ValidityReport block",
            error=f"raw output (first 600 chars): {full_text[:600]}",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    # Normalize + coerce into a safe shape for the frontend.
    overall = str(parsed.get("overall", "")).strip().lower()
    if overall not in VALID_OVERALL:
        overall = "acceptable"  # safe default rather than propagating garbage
    summary_text = str(parsed.get("summary", "")).strip()
    confidence = parsed.get("confidence", 0.0)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    checks_raw = parsed.get("checks") or []
    checks: list[dict[str, Any]] = []
    for c in checks_raw:
        if not isinstance(c, dict):
            continue
        label = str(c.get("label", "")).strip().lower()
        mark = str(c.get("mark", "")).strip().lower()
        note = str(c.get("note", "")).strip()
        if label not in VALID_LABELS:
            continue
        if mark not in VALID_MARKS:
            mark = "warn"
        checks.append({"label": label, "mark": mark, "note": note})

    payload = {
        "overall": overall,
        "summary": summary_text,
        "confidence": confidence,
        "checks": checks,
    }

    return SubagentResult(
        ok=True,
        summary=summary_text or f"validity: {overall}",
        payload=payload,
        cost_usd=total_cost,
        duration_ms=duration_ms,
    )
