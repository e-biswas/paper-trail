"""Metric Extractor subagent.

Normalises raw eval-script stdout into a list of canonical `MetricResult`
dicts so the dossier can render typed before/after comparisons without
free-form string parsing.

Tool-free (text-in / text-out). The conductor runs the eval via the
Experiment Runner subagent, then hands stdout here for normalisation.

See `docs/backend/subagents.md` for the role + schema and
`docs/integration.md` for the structured `metric_delta` payload that
consumes these results.
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
    extract_all_result_blocks,
    load_subagent_prompt,
)

log = logging.getLogger(__name__)


VALID_SPLITS: tuple[str, ...] = ("train", "val", "test", "other")


async def extract(
    stdout: str,
    *,
    max_budget_usd: float = 0.30,
    max_turns: int = 2,
) -> SubagentResult:
    """Return a `SubagentResult` whose payload `metrics` list holds one
    `MetricResult` dict per metric identified in `stdout`.
    """
    if not stdout or not stdout.strip():
        return SubagentResult(ok=False, summary="empty stdout", error="empty_input")

    system_prompt = load_subagent_prompt("metric_extractor")

    # Keep the input compact — eval stdout is usually short, but some
    # runs emit progress bars or chatter; truncate the head if needed.
    MAX_CHARS = 12_000
    body = stdout
    if len(body) > MAX_CHARS:
        head = body[: MAX_CHARS // 4]
        tail = body[-(MAX_CHARS - MAX_CHARS // 4) :]
        body = f"{head}\n\n[... {len(stdout) - MAX_CHARS} chars elided ...]\n\n{tail}"

    prompt = (
        "Eval-script stdout follows. Extract every numeric metric it reports "
        "and emit one `## Metric:` block per metric per your operating contract. "
        "Emit nothing else.\n\n"
        "------------------\n"
        f"{body}\n"
        "------------------"
    )

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
    blocks = extract_all_result_blocks(full_text, expected_kind="Metric")
    if not blocks:
        return SubagentResult(
            ok=False,
            summary="metric_extractor did not emit any Metric blocks",
            error=f"raw output (first 500 chars): {full_text[:500]}",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    metrics: list[dict[str, Any]] = []
    for parsed in blocks:
        metric = _normalise_metric(parsed)
        if metric is not None:
            metrics.append(metric)

    if not metrics:
        return SubagentResult(
            ok=False,
            summary="every Metric block was malformed after normalisation",
            payload={"raw_blocks": blocks},
            error="no_valid_metrics",
            cost_usd=total_cost,
            duration_ms=duration_ms,
        )

    return SubagentResult(
        ok=True,
        summary=f"extracted {len(metrics)} metric(s)",
        payload={"metrics": metrics},
        cost_usd=total_cost,
        duration_ms=duration_ms,
    )


def _normalise_metric(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce a raw Metric block dict into the canonical `MetricResult` shape.

    Returns None when required fields are missing / unusable.
    """
    name = parsed.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    value_raw = parsed.get("value")
    try:
        value = float(value_raw)
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN check
        return None

    split_raw = parsed.get("split", "other")
    split = str(split_raw).strip().lower() if split_raw is not None else "other"
    if split not in VALID_SPLITS:
        split = "other"

    context = str(parsed.get("context", "")).strip()

    result: dict[str, Any] = {
        "name": name.strip(),
        "value": value,
        "split": split,
        "context": context,
    }

    ci_raw = parsed.get("confidence_interval")
    if isinstance(ci_raw, list) and len(ci_raw) == 2:
        try:
            lo = float(ci_raw[0])
            hi = float(ci_raw[1])
            if lo <= hi:
                result["confidence_interval"] = [lo, hi]
        except (TypeError, ValueError):
            pass

    return result
