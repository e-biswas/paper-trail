"""Minimal SDK smoke test.

Purpose: verify (a) the API key in `.env` authenticates successfully,
(b) `claude_agent_sdk.query()` streams messages on Opus 4.7, and
(c) `include_partial_messages=True` emits fine-grained `StreamEvent`s
(the explicit Day-1 risk from the plan).

Deliberately tiny: prompt is a single-token-ish response, no tools,
`max_turns=1`, `max_budget_usd=0.50` as a safety cap. Expected cost ≪ $0.01.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    UserMessage,
    query,
)

from server.env import load_env


def _summary(label: str, value: object) -> None:
    print(f"  {label:30s} {value}")


async def _run_probe(*, include_partial: bool) -> dict:
    """Run the same tiny prompt twice: once with streaming off, once on.

    Count messages + partial StreamEvents so we can report whether the
    fine-grained streaming path is live on Opus 4.7.
    """
    options = ClaudeAgentOptions(
        model="claude-opus-4-7",
        system_prompt="Reply with the exact word `pong` and nothing else.",
        allowed_tools=[],
        max_turns=1,
        max_budget_usd=0.50,
        include_partial_messages=include_partial,
    )

    started = time.monotonic()
    counts = {
        "system": 0,
        "assistant": 0,
        "user": 0,
        "result": 0,
        "stream_event": 0,
        "text_chars": 0,
    }
    assistant_text = ""
    total_cost = 0.0
    num_turns = 0
    is_error = False
    stop_reason: str | None = None

    async for msg in query(prompt="ping", options=options):
        if isinstance(msg, SystemMessage):
            counts["system"] += 1
            continue
        if isinstance(msg, AssistantMessage):
            counts["assistant"] += 1
            for block in msg.content:
                if isinstance(block, TextBlock):
                    assistant_text += block.text
                    counts["text_chars"] += len(block.text)
            continue
        if isinstance(msg, UserMessage):
            counts["user"] += 1
            continue
        if isinstance(msg, StreamEvent):
            counts["stream_event"] += 1
            continue
        if isinstance(msg, ResultMessage):
            counts["result"] += 1
            total_cost = float(getattr(msg, "total_cost_usd", 0.0) or 0.0)
            num_turns = int(getattr(msg, "num_turns", 0) or 0)
            is_error = bool(getattr(msg, "is_error", False))
            stop_reason = getattr(msg, "stop_reason", None)
            break

    return {
        "include_partial": include_partial,
        "elapsed_s": round(time.monotonic() - started, 3),
        "counts": counts,
        "assistant_text": assistant_text.strip(),
        "total_cost_usd": total_cost,
        "num_turns": num_turns,
        "is_error": is_error,
        "stop_reason": stop_reason,
    }


async def main() -> int:
    try:
        load_env()
    except Exception as exc:
        print(f"FAIL: env load: {exc}")
        return 1

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key or key.lower() in {"stub", "fake", "test"}:
        print(f"FAIL: ANTHROPIC_API_KEY not set or placeholder ({key!r})")
        return 1

    print(f"API key loaded. key length={len(key)} chars, prefix={key[:7]}***")
    print()

    print("── Probe A: include_partial_messages=False (whole-message mode) ──")
    try:
        result_a = await _run_probe(include_partial=False)
    except Exception as exc:
        print(f"FAIL during probe A: {type(exc).__name__}: {exc}")
        return 1
    for k in ("elapsed_s", "assistant_text", "counts", "total_cost_usd", "num_turns", "is_error", "stop_reason"):
        _summary(k, result_a[k])
    print()

    print("── Probe B: include_partial_messages=True (fine-grained streaming) ──")
    try:
        result_b = await _run_probe(include_partial=True)
    except Exception as exc:
        print(f"FAIL during probe B: {type(exc).__name__}: {exc}")
        return 1
    for k in ("elapsed_s", "assistant_text", "counts", "total_cost_usd", "num_turns", "is_error", "stop_reason"):
        _summary(k, result_b[k])
    print()

    # ── Verdict ─────────────────────────────────────────────────────────
    print("── Verdict ──")
    passed = True

    if result_a["is_error"] or result_b["is_error"]:
        print("  ✗ SDK reported is_error=True on at least one run")
        passed = False
    else:
        print("  ✓ Both probes completed without SDK error")

    if "pong" in result_a["assistant_text"].lower() and "pong" in result_b["assistant_text"].lower():
        print("  ✓ Both probes returned the expected 'pong' token")
    else:
        print(f"  ✗ Expected 'pong' in both replies; got {result_a['assistant_text']!r} and {result_b['assistant_text']!r}")
        passed = False

    total_cost = result_a["total_cost_usd"] + result_b["total_cost_usd"]
    if total_cost < 0.05:
        print(f"  ✓ Total cost of probes: ${total_cost:.5f} (well under the $0.50 cap)")
    else:
        print(f"  ! Total cost higher than expected: ${total_cost:.5f}")

    # The Day-1 risk check: does include_partial_messages=True actually surface
    # StreamEvents? If the count is 0, the UI can't render fine-grained text.
    if result_b["counts"]["stream_event"] > 0:
        print(f"  ✓ include_partial_messages=True emitted {result_b['counts']['stream_event']} StreamEvents "
              "(fine-grained streaming is live on Opus 4.7)")
    else:
        print("  ! include_partial_messages=True produced zero StreamEvents — "
              "the Day-1 risk. We'll need to fall back to whole-message events for the UI.")
        # Not a hard failure; documented fallback exists.

    print()
    if passed:
        print("SMOKE PASS — API key authenticates and streaming works.")
        return 0
    print("SMOKE FAIL — see above.")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
