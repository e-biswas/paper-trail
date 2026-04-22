"""End-to-end test — Quick Check mode against the Muchlinski fixture.

Runs three canned Quick Check prompts, verifies each returns a single
`quick_check_verdict` envelope with a reasonable verdict/confidence/evidence
payload in well under the turn cap.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

from server.agent import RunConfig, run_agent
from server.env import load_env

ROOT = Path(__file__).resolve().parent.parent
REPO_PATH = Path("/tmp/muchlinski-demo")


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


def _reset_fixture() -> None:
    stage = ROOT / "demo" / "primary" / "stage.sh"
    subprocess.run([str(stage)], check=True, capture_output=True, text=True)


async def _run_one(case: dict) -> tuple[bool, float, float]:
    """Run one Quick Check. Returns (passed, duration_s, cost_usd)."""
    question = case["question"]
    must_mention = case["must_mention"]
    min_evidence = case.get("min_evidence", 1)

    print(f"  Q: {question}")
    config = RunConfig.from_dict(
        mode="check",
        run_id=f"qc-e2e-{int(time.time()*1000)}",
        raw={
            "repo_path": str(REPO_PATH),
            "question": question,
            "max_budget_usd": 1.0,
        },
    )

    t0 = time.monotonic()
    verdict_event = None
    tool_calls = 0
    cost = 0.0
    async for ev in run_agent(config):
        if ev["type"] == "tool_call":
            tool_calls += 1
        elif ev["type"] == "quick_check_verdict":
            verdict_event = ev["data"]
        elif ev["type"] == "session_end":
            cost = float(ev["data"].get("cost_usd", 0.0))
            break
    duration = time.monotonic() - t0

    passed = True
    if verdict_event is None:
        passed &= _ok("quick_check_verdict emitted", False, "no verdict")
        return passed, duration, cost

    passed &= _ok(
        "verdict ∈ {confirmed, refuted, unclear}",
        verdict_event.get("verdict") in ("confirmed", "refuted", "unclear"),
        f"got {verdict_event.get('verdict')!r}",
    )
    passed &= _ok(
        "confidence >= 0.6",
        float(verdict_event.get("confidence", 0.0)) >= 0.6,
        f"{verdict_event.get('confidence')}",
    )
    evidence = verdict_event.get("evidence") or []
    passed &= _ok(
        f"≥{min_evidence} evidence entry",
        len(evidence) >= min_evidence,
        f"{len(evidence)} entries",
    )
    # Evidence-content check — verdict should reference the signal we expect
    # the agent to find. Looks at evidence snippets + notes for any keyword.
    notes = str(verdict_event.get("notes", "")).lower()
    evidence_blob = " ".join(
        str(e.get("snippet", "") or "") + " " + str(e.get("file", "") or "")
        for e in evidence
        if isinstance(e, dict)
    ).lower()
    haystack = notes + " " + evidence_blob
    mention_hit = any(kw.lower() in haystack for kw in must_mention)
    passed &= _ok(
        f"evidence or notes mentions one of {must_mention}",
        mention_hit,
        f"notes='{notes[:80]}…'",
    )
    passed &= _ok(
        "turn cap respected (≤ 15 tool calls)",
        tool_calls <= 15,
        f"{tool_calls} tool calls",
    )
    passed &= _ok(
        "duration < 45s",
        duration < 45,
        f"{duration:.1f}s",
    )
    print(f"    verdict: {verdict_event.get('verdict')!r}, confidence: {verdict_event.get('confidence')}")
    print(f"    cost: ${cost:.5f}")
    return passed, duration, cost


async def main() -> int:
    load_env()
    print("── prep ──")
    _reset_fixture()

    cases = [
        # Canned prompts per docs/backend/prompts.md. Each case declares the
        # evidence keyword set that MUST appear in the verdict's notes /
        # evidence for the check to pass. This is more robust than pinning
        # to a specific verdict label, since "confirmed" vs "refuted"
        # depends on how the question is phrased.
        {
            "question": "Is the imputer fit only on training data (not on the full dataframe)?",
            "must_mention": ("full", "train_test_split", "before"),
            "min_evidence": 1,
        },
        {
            "question": "Are there exact-duplicate rows between train and test splits?",
            "must_mention": ("duplicate", "drop_duplicates", "unique"),
            "min_evidence": 1,
        },
        {
            "question": "Does the target column appear as a feature at any point in the pipeline?",
            "must_mention": ("civil_war_onset", "target"),
            "min_evidence": 1,
        },
    ]

    total_cost = 0.0
    total_passed = True
    for case in cases:
        print()
        print("── Quick Check ──")
        passed, _, cost = await _run_one(case)
        total_passed &= passed
        total_cost += cost

    print()
    print(f"total cost: ${total_cost:.5f}")
    if total_passed:
        print("QUICK CHECK E2E PASS")
        return 0
    print("QUICK CHECK E2E FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
