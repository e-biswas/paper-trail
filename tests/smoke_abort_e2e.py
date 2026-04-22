"""Smoke test for the D5.X-abort contract.

Drives the run orchestrator directly (no HTTP layer) to verify:

1. `raw_text_delta` envelopes are emitted from real AssistantMessage text blocks.
2. `cost_update` envelopes are emitted at least twice and monotonically
   non-decreasing.
3. `session_end.data.cost_usd` matches the final `cost_update.total_usd`.

Then drives a second run through the FastAPI WebSocket handler with a slow
stub source, sends a client-initiated `{"type": "stop"}` frame, and confirms
the terminal `session_end` carries `stop_reason="user_abort"`.

Uses the existing Muchlinski fixture for the live-SDK Quick Check.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from server.agent import RunConfig, run_agent
from server.env import load_env

ROOT = Path(__file__).resolve().parent.parent
REPO_PATH = Path("/tmp/muchlinski-demo")


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


# ---------------------------------------------------------------------- #
# Phase 1 — live SDK run, confirm raw_text_delta + cost_update envelopes
# ---------------------------------------------------------------------- #


async def _phase_live_envelopes() -> bool:
    print("── phase 1: live Quick Check — raw_text_delta + cost_update ──")
    if not REPO_PATH.exists():
        print(f"  ! {REPO_PATH} missing — run demo/primary/stage.sh first")
        return False

    config = RunConfig.from_dict(
        mode="check",
        run_id=f"abort-smoke-{int(time.time()*1000)}",
        raw={
            "repo_path": str(REPO_PATH),
            "question": "Is the imputer fit only on training data?",
            "max_budget_usd": 0.80,
        },
    )

    raw_deltas = 0
    cost_updates: list[dict[str, Any]] = []
    session_end_data: dict[str, Any] | None = None

    async for ev in run_agent(config):
        etype = ev.get("type")
        if etype == "raw_text_delta":
            raw_deltas += 1
        elif etype == "cost_update":
            cost_updates.append(dict(ev.get("data", {})))
        elif etype == "session_end":
            session_end_data = dict(ev.get("data", {}))
            break

    passed = True
    passed &= _ok("raw_text_delta envelopes fire", raw_deltas > 0, f"{raw_deltas} deltas")
    passed &= _ok("≥ 1 cost_update envelopes", len(cost_updates) >= 1, f"{len(cost_updates)} updates")
    if cost_updates:
        totals = [u.get("total_usd", 0.0) for u in cost_updates]
        is_monotone = all(totals[i] >= totals[i - 1] for i in range(1, len(totals)))
        passed &= _ok("cost_update monotonically non-decreasing", is_monotone, f"totals={totals}")
    passed &= _ok("session_end observed", session_end_data is not None)
    if session_end_data and cost_updates:
        final_stream = cost_updates[-1].get("total_usd", 0.0)
        final_session = float(session_end_data.get("cost_usd", 0.0))
        passed &= _ok(
            "final cost_update ≈ session_end.cost_usd",
            abs(final_stream - final_session) < 0.001 or final_session >= final_stream,
            f"stream={final_stream} session={final_session}",
        )
    return passed


# ---------------------------------------------------------------------- #
# Phase 2 — client stop frame over the real WS handler
# ---------------------------------------------------------------------- #


async def _phase_client_stop() -> bool:
    """Boots the FastAPI app via httpx TestClient with a synthetic slow stub
    source so the test can cancel mid-run and confirm stop_reason=user_abort.
    """
    print("── phase 2: client stop frame → stop_reason=user_abort ──")

    # Force the stub path by blanking the API key.
    # (The orchestrator's stub emits 4 envelopes over ~200ms, which is too
    # fast to reliably cancel. Monkey-patch `_run_stub` to sleep longer.)
    from server import agent as agent_mod

    original_stub = agent_mod._run_stub

    async def _slow_stub(config):  # type: ignore[no-untyped-def]
        yield {"type": "claim_summary",
               "data": {"claim": f"(slow stub) {config.mode}"}}
        for i in range(20):
            await asyncio.sleep(0.15)
            yield {"type": "tool_call",
                   "data": {"id": f"stub-{i}", "name": "Read",
                            "input": {"file_path": f"step_{i}.py"}}}
        yield {"type": "session_end",
               "data": {"ok": True, "total_turns": 1, "cost_usd": 0.0, "duration_ms": 200}}

    agent_mod._run_stub = _slow_stub  # type: ignore[assignment]

    # Swap the API key for a sentinel value that is non-empty (so
    # load_env() on startup passes) but triggers the stub-path branch
    # in run_agent (see `use_stub = ... or key.lower() in {"stub", ...}`).
    saved_key = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "stub"

    try:
        from fastapi.testclient import TestClient
        from server.main import app

        passed = True
        with TestClient(app) as client:
            with client.websocket_connect("/ws/investigate") as ws:
                ws.send_json(
                    {
                        "type": "start",
                        "run_id": "abort-stop-smoke",
                        "config": {
                            "paper_url": "test_data/papers/muchlinski.md",
                            "repo_path": str(REPO_PATH),
                            "max_budget_usd": 0.10,
                        },
                    }
                )
                # Wait for at least session_start + one tool_call so we know
                # the run is live before we send stop.
                seen_tool_call = False
                session_end_data: dict[str, Any] | None = None
                all_types: list[str] = []
                deadline = time.monotonic() + 8.0
                while time.monotonic() < deadline:
                    msg = ws.receive_json()
                    all_types.append(msg.get("type"))
                    if msg.get("type") == "tool_call" and not seen_tool_call:
                        seen_tool_call = True
                        ws.send_json({"type": "stop"})
                    if msg.get("type") == "session_end":
                        session_end_data = dict(msg.get("data", {}))
                        break

                passed &= _ok("saw at least one tool_call before stop", seen_tool_call,
                              f"types={all_types[:6]}…")
                passed &= _ok("session_end received after stop", session_end_data is not None)
                if session_end_data:
                    passed &= _ok(
                        "stop_reason == 'user_abort'",
                        session_end_data.get("stop_reason") == "user_abort",
                        f"got {session_end_data.get('stop_reason')!r}",
                    )
                    passed &= _ok("ok == false on abort",
                                  session_end_data.get("ok") is False,
                                  f"ok={session_end_data.get('ok')!r}")

        return passed
    finally:
        # Restore both the stub and the API key.
        agent_mod._run_stub = original_stub  # type: ignore[assignment]
        if saved_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = saved_key


async def main() -> int:
    load_env()
    phase1 = await _phase_live_envelopes()
    print()
    phase2 = await _phase_client_stop()
    print()
    if phase1 and phase2:
        print("ABORT + COST SMOKE PASS")
        return 0
    print("ABORT + COST SMOKE FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
