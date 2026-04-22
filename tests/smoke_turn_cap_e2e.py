"""Smoke test for the turn-cap → synthesized `aborted` envelope.

Forces the SDK path to hit `max_turns` without emitting a verdict and
confirms:

1. The orchestrator yields an `aborted` envelope with `reason="turn_cap"`
   and a `detail` that names the budget.
2. The subsequent `session_end` carries `stop_reason="turn_cap"` and
   `ok=false`.
3. The frontend state reducer lands on `status="aborted"` and keeps the
   aborted payload available for the AssistantMessage banner.
4. The frontend label map used in `AssistantMessage.tsx` has a
   human-readable entry for `turn_cap`.

We bypass the real Claude API by monkey-patching `claude_agent_sdk.query`
with a synthetic async generator that yields lots of empty AssistantMessages
until `max_turns` would be hit, then returns a ResultMessage with
`stop_reason="max_turns"`.
"""
from __future__ import annotations

import asyncio
import re
import sys
import types
from pathlib import Path
from typing import Any

from server.env import load_env
from server import agent as agent_mod
from server.agent import RunConfig, TURN_BUDGETS, run_agent

REPO_PATH = Path("/tmp/muchlinski-demo")
ROOT = Path(__file__).resolve().parent.parent
FRONTEND_LABEL_FILE = ROOT / "web" / "src" / "components" / "chat" / "AssistantMessage.tsx"


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


# ---------------------------------------------------------------------- #
# Synthetic SDK generator that exhausts max_turns without a verdict
# ---------------------------------------------------------------------- #


def _install_fake_sdk_query() -> None:
    """Replace `claude_agent_sdk.query` with a generator that stops at the
    cap. The agent_mod's `_run_sdk` imports the SDK lazily via `from ... import`,
    so we patch the module the SDK lives in — the re-imported names resolve
    to our fakes on the next call.
    """
    import claude_agent_sdk as sdk

    real_classes = {
        "AssistantMessage": sdk.AssistantMessage,
        "ClaudeAgentOptions": sdk.ClaudeAgentOptions,
        "ResultMessage": sdk.ResultMessage,
        "SystemMessage": sdk.SystemMessage,
        "TextBlock": sdk.TextBlock,
        "ToolResultBlock": sdk.ToolResultBlock,
        "ToolUseBlock": sdk.ToolUseBlock,
        "UserMessage": sdk.UserMessage,
    }

    async def fake_query(*, prompt: str, options: Any):  # noqa: ARG001
        """Emit max_turns+1 AssistantMessages with throwaway prose, never a
        `## Verdict:` block, then a ResultMessage with stop_reason="max_turns".
        """
        cap = int(getattr(options, "max_turns", 8) or 8)
        for i in range(cap):
            # Each AssistantMessage has a non-verdict TextBlock.
            msg = real_classes["AssistantMessage"](
                content=[real_classes["TextBlock"](
                    text=f"I'm looking at the repo step {i + 1}, still thinking...\n"
                )],
                model=getattr(options, "model", "claude-opus-4-7"),
                usage={"input_tokens": 10, "output_tokens": 5},
            )
            yield msg
            await asyncio.sleep(0)
        # Final ResultMessage: SDK says it hit the cap.
        yield real_classes["ResultMessage"](
            subtype="error",
            duration_ms=1000,
            duration_api_ms=800,
            is_error=False,
            num_turns=cap,
            session_id="fake-session",
            stop_reason="max_turns",
            total_cost_usd=0.01,
            usage={"input_tokens": 10 * cap, "output_tokens": 5 * cap},
        )

    sdk.query = fake_query


# ---------------------------------------------------------------------- #
# Phase 1 — backend synthesizes aborted + session_end(stop_reason=turn_cap)
# ---------------------------------------------------------------------- #


async def _phase_backend_turn_cap() -> bool:
    print("── phase 1: backend synthesizes aborted on turn_cap ──")
    _install_fake_sdk_query()

    config = RunConfig.from_dict(
        mode="check",  # smaller cap = faster test; same code path for investigate
        run_id="turn-cap-smoke",
        raw={
            "repo_path": str(REPO_PATH),
            "question": "Is the imputer fit only on training data?",
            "max_budget_usd": 0.10,
        },
    )

    envelopes: list[dict[str, Any]] = []
    async for ev in run_agent(config):
        envelopes.append(ev)
        if ev.get("type") == "session_end":
            break

    types_seen = [e.get("type") for e in envelopes]
    passed = True
    passed &= _ok("envelope stream not empty", len(envelopes) > 0, f"types={types_seen[:6]}…")

    aborted = next((e for e in envelopes if e.get("type") == "aborted"), None)
    passed &= _ok("`aborted` envelope synthesized", aborted is not None)
    if aborted:
        data = aborted.get("data") or {}
        passed &= _ok(
            "aborted.reason == 'turn_cap'",
            data.get("reason") == "turn_cap",
            f"got {data.get('reason')!r}",
        )
        detail = str(data.get("detail", ""))
        passed &= _ok(
            "aborted.detail names the budget (e.g. '15-turn')",
            bool(re.search(r"\b\d+-turn\b", detail)),
            f"detail={detail!r}",
        )

    session_end = next(
        (e for e in envelopes if e.get("type") == "session_end"), None
    )
    passed &= _ok("session_end observed", session_end is not None)
    if session_end:
        data = session_end.get("data") or {}
        passed &= _ok(
            "session_end.stop_reason == 'turn_cap'",
            data.get("stop_reason") == "turn_cap",
            f"got {data.get('stop_reason')!r}",
        )
        passed &= _ok("session_end.ok is False", data.get("ok") is False)
        passed &= _ok(
            "session_end.total_turns ≈ cap",
            int(data.get("total_turns", 0)) >= TURN_BUDGETS["check"] - 1,
            f"turns={data.get('total_turns')}",
        )

    # Ordering: aborted must precede session_end.
    try:
        aborted_idx = types_seen.index("aborted")
        session_end_idx = types_seen.index("session_end")
        passed &= _ok(
            "aborted arrives before session_end",
            aborted_idx < session_end_idx,
            f"aborted@{aborted_idx}, session_end@{session_end_idx}",
        )
    except ValueError:
        pass  # already reported above

    return passed


# ---------------------------------------------------------------------- #
# Phase 2 — frontend aborted banner has a human-readable label for turn_cap
# ---------------------------------------------------------------------- #


def _phase_frontend_label() -> bool:
    print("── phase 2: frontend AssistantMessage.tsx has a turn_cap label ──")
    if not FRONTEND_LABEL_FILE.exists():
        print(f"  ! {FRONTEND_LABEL_FILE} missing")
        return False
    txt = FRONTEND_LABEL_FILE.read_text(encoding="utf-8")
    passed = True
    passed &= _ok(
        "ABORT_REASON_LABEL map exists",
        "ABORT_REASON_LABEL" in txt,
    )
    passed &= _ok(
        "turn_cap has a user-facing label",
        bool(re.search(r"turn_cap\s*:\s*['\"][^'\"]+", txt)),
    )
    passed &= _ok(
        "banner renders ABORT_REASON_LABEL value",
        "ABORT_REASON_LABEL[" in txt and "s.aborted.reason" in txt,
    )
    return passed


# ---------------------------------------------------------------------- #
# Phase 3 — confirm new budgets ship through the public surface
# ---------------------------------------------------------------------- #


def _phase_budget_constants() -> bool:
    print("── phase 3: TURN_BUDGETS reflect the new caps ──")
    passed = True
    passed &= _ok(
        "TURN_BUDGETS['investigate'] == 50",
        TURN_BUDGETS["investigate"] == 50,
        f"got {TURN_BUDGETS['investigate']}",
    )
    passed &= _ok(
        "TURN_BUDGETS['check'] == 15",
        TURN_BUDGETS["check"] == 15,
        f"got {TURN_BUDGETS['check']}",
    )

    # Frontend composer tagline mirrors the new numbers.
    input_row = ROOT / "web" / "src" / "components" / "chat" / "InputRow.tsx"
    txt = input_row.read_text(encoding="utf-8")
    passed &= _ok("frontend tagline says '≤50 turns'", "≤50 turns" in txt)
    passed &= _ok("frontend tagline says '≤15 turns'", "≤15 turns" in txt)
    return passed


async def main() -> int:
    load_env()

    p3 = _phase_budget_constants()
    print()
    p2 = _phase_frontend_label()
    print()
    p1 = await _phase_backend_turn_cap()
    print()

    if p1 and p2 and p3:
        print("TURN-CAP SMOKE PASS")
        return 0
    print("TURN-CAP SMOKE FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
