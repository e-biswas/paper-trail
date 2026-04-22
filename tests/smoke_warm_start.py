"""Smoke test for the warm-start block on aborted prior runs.

Seeds the RunStore with a fake aborted Deep Investigation (hypothesis +
check + finding + tool_call events, then `aborted` + `session_end(stop_reason
="turn_cap")`), then drives `_build_session_context_block` for a follow-up
run in the same session. Asserts:

- When the prior run was aborted, the warm-start block is present and
  carries the hypotheses, checks+findings, and files inspected.
- When the prior run succeeded (verdict emitted), no warm-start block is
  generated — only the plain "Prior context" summary.
- When there is no prior run, the session context is empty.
- `summarize_partial_progress` returns None for an empty run and a
  well-shaped dict for a run with events.

This test uses a temporary RunStore pointed at a throwaway directory so it
doesn't touch the real `~/.paper-trail/runs/` store.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from server import agent as agent_mod
from server.runs import RunMeta, RunStore
from server.runs import _STORE as _MODULE_STORE  # type: ignore[attr-defined]

import server.runs as runs_module


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


def _install_temp_store() -> tuple[RunStore, Path]:
    tmp = Path(tempfile.mkdtemp(prefix="paper-trail-warm-start-"))
    store = RunStore(root=tmp)
    runs_module._STORE = store
    return store, tmp


def _teardown(tmp: Path, saved: RunStore | None) -> None:
    runs_module._STORE = saved
    shutil.rmtree(tmp, ignore_errors=True)


def _seed_aborted_run(store: RunStore, *, session_id: str, run_id: str) -> None:
    """Write a realistic aborted Deep Investigation to the store."""
    store.begin_run(
        run_id=run_id,
        mode="investigate",
        session_id=session_id,
        config={
            "paper_url": "test_data/papers/muchlinski.md",
            "repo_path": "/tmp/muchlinski-demo",
            "repo_slug": None,
            "model": "claude-opus-4-7",
        },
    )
    envelopes = [
        {"type": "session_start", "data": {"mode": "investigate"}},
        {"type": "claim_summary", "data": {"claim": "RF > LR on civil-war onset."}},
        {"type": "hypothesis", "data": {
            "id": "h1", "rank": 1, "name": "Imputation-before-split leakage",
            "confidence": 0.72, "reason": "KNN imputer appears to fit the full df.",
        }},
        {"type": "hypothesis", "data": {
            "id": "h2", "rank": 2, "name": "Class-imbalance handling mismatch",
            "confidence": 0.45, "reason": "Imbalanced labels without stratified split.",
        }},
        {"type": "hypothesis", "data": {
            "id": "h3", "rank": 3, "name": "Feature target leakage",
            "confidence": 0.30, "reason": "Target column may appear as a feature.",
        }},
        {"type": "tool_call", "data": {
            "id": "tu1", "name": "Read",
            "input": {"file_path": "src/prepare_data.py"},
        }},
        {"type": "tool_result", "data": {
            "id": "tu1", "name": "Read", "output": "...", "is_error": False, "duration_ms": 80,
        }},
        {"type": "check", "data": {
            "id": "c1", "hypothesis_id": "h1",
            "description": "Inspect imputation order",
            "method": "Read prepare_data.py",
        }},
        {"type": "finding", "data": {
            "id": "f1", "check_id": "c1",
            "result": "Imputer fit on full df at line 28, before train_test_split.",
            "supports": ["h1"], "refutes": [],
        }},
        {"type": "hypothesis_update", "data": {
            "id": "h1", "confidence": 0.88,
            "reason_delta": "Confirmed by src/prepare_data.py line 28.",
        }},
        # ... then the run stalls; no verdict reached before turn_cap ...
        {"type": "aborted", "data": {
            "reason": "turn_cap",
            "detail": "Run exhausted 50-turn budget without producing a verdict.",
        }},
        {"type": "session_end", "data": {
            "ok": False,
            "stop_reason": "turn_cap",
            "total_turns": 50,
            "cost_usd": 1.12,
            "duration_ms": 180_000,
        }},
    ]
    for ev in envelopes:
        store.append_event(run_id, ev)
        store.update_meta_from_event(run_id, ev)


def _seed_success_run(store: RunStore, *, session_id: str, run_id: str) -> None:
    """Write a realistic successful Deep Investigation to the store."""
    store.begin_run(
        run_id=run_id,
        mode="investigate",
        session_id=session_id,
        config={
            "paper_url": "test_data/papers/muchlinski.md",
            "repo_path": "/tmp/muchlinski-demo",
            "repo_slug": "bot/muchlinski",
            "model": "claude-opus-4-7",
        },
    )
    envelopes = [
        {"type": "hypothesis", "data": {
            "id": "h1", "rank": 1, "name": "Imputation leakage",
            "confidence": 0.9, "reason": "Fit on full df.",
        }},
        {"type": "verdict", "data": {
            "hypothesis_id": "h1", "confidence": 0.94,
            "summary": "Imputation-before-split leakage confirmed on prepare_data.py:28.",
        }},
        {"type": "fix_applied", "data": {
            "files_changed": ["src/prepare_data.py"],
            "diff_summary": "Moved KNNImputer inside sklearn Pipeline.",
        }},
        {"type": "metric_delta", "data": {
            "metric": "AUC", "before": 0.9562, "after": 0.9070,
            "context": "RF, Muchlinski, 5-fold CV",
        }},
        {"type": "session_end", "data": {
            "ok": True, "total_turns": 14, "cost_usd": 0.74, "duration_ms": 134_000,
        }},
    ]
    for ev in envelopes:
        store.append_event(run_id, ev)
        store.update_meta_from_event(run_id, ev)


# ---------------------------------------------------------------------- #
# Phases
# ---------------------------------------------------------------------- #


def _phase_partial_progress_summary(store: RunStore) -> bool:
    print("── phase 1: summarize_partial_progress returns correct shape ──")
    _seed_aborted_run(store, session_id="sess-1", run_id="aborted-1")

    summary = store.summarize_partial_progress("aborted-1")
    passed = True
    passed &= _ok("summary not None", summary is not None)
    if summary is None:
        return passed

    hypotheses = summary.get("hypotheses") or []
    passed &= _ok("3 hypotheses captured", len(hypotheses) == 3, f"got {len(hypotheses)}")
    # h1 should come first (highest confidence after update 0.88)
    first = hypotheses[0] if hypotheses else {}
    passed &= _ok(
        "h1 ranked first by updated confidence",
        first.get("id") == "h1",
        f"got {first.get('id')}",
    )
    passed &= _ok(
        "h1 confidence reflects hypothesis_update (~0.88)",
        abs(float(first.get("confidence", 0)) - 0.88) < 0.001,
        f"{first.get('confidence')}",
    )
    passed &= _ok(
        "h1 carries reason_delta from update",
        "prepare_data.py" in (first.get("reason_delta") or ""),
    )

    checks = summary.get("checks") or []
    passed &= _ok("1 check captured", len(checks) == 1, f"got {len(checks)}")
    if checks:
        passed &= _ok(
            "c1 finding merged in",
            "Imputer fit on full df" in (checks[0].get("finding") or ""),
        )

    files = summary.get("files_inspected") or []
    passed &= _ok(
        "prepare_data.py in files_inspected",
        "src/prepare_data.py" in files,
    )
    passed &= _ok(
        "total_events > 0",
        int(summary.get("total_events", 0)) > 5,
        f"{summary.get('total_events')}",
    )

    # Empty-run case.
    empty = store.summarize_partial_progress("nonexistent-run")
    passed &= _ok("unknown run_id → None", empty is None)
    return passed


def _phase_warm_start_block_on_aborted(store: RunStore) -> bool:
    print("── phase 2: _build_session_context_block splices warm-start on abort ──")
    # Seed already done by phase 1 (same session). Build context from the
    # perspective of a NEW run in the same session.
    ctx = agent_mod._build_session_context_block("sess-1", exclude_run_id="follow-up")

    passed = True
    passed &= _ok("context block not empty", bool(ctx), f"len={len(ctx)}")
    passed &= _ok(
        "contains 'Prior context' header",
        "## Prior context from this session" in ctx,
    )
    passed &= _ok(
        "marks prior run as aborted(turn_cap) in the summary",
        "status: aborted (turn_cap)" in ctx,
    )
    passed &= _ok(
        "warm-start block present",
        "## Partial progress from the previous aborted attempt" in ctx,
    )
    passed &= _ok("mentions 50-turn budget", "50 turn" in ctx)
    passed &= _ok("lists h1 hypothesis", "h1" in ctx and "Imputation-before-split leakage" in ctx)
    passed &= _ok("lists updated confidence 0.88", "0.88" in ctx)
    passed &= _ok(
        "lists c1 check with finding",
        "c1" in ctx and "Imputer fit on full df" in ctx,
    )
    passed &= _ok(
        "lists inspected file",
        "src/prepare_data.py" in ctx,
    )
    passed &= _ok(
        "has 'warm priors, not ground truth' guidance",
        "warm priors, not ground truth" in ctx,
    )
    passed &= _ok(
        "has 'Do NOT repeat checks' instruction",
        "Do NOT repeat checks" in ctx,
    )
    return passed


def _phase_no_warm_start_on_success(store: RunStore) -> bool:
    print("── phase 3: no warm-start when prior run succeeded ──")
    _seed_success_run(store, session_id="sess-success", run_id="success-1")
    ctx = agent_mod._build_session_context_block("sess-success", exclude_run_id="follow-up")

    passed = True
    passed &= _ok("context block not empty", bool(ctx))
    passed &= _ok(
        "'Prior context' section present",
        "## Prior context from this session" in ctx,
    )
    passed &= _ok(
        "verdict summary carried forward",
        "Imputation-before-split leakage confirmed" in ctx,
    )
    passed &= _ok(
        "NO warm-start block (prior was success)",
        "## Partial progress from the previous aborted attempt" not in ctx,
    )
    return passed


def _phase_no_context_without_session(store: RunStore) -> bool:
    print("── phase 4: no context when session_id missing ──")
    ctx = agent_mod._build_session_context_block(None, exclude_run_id="x")
    passed = _ok("empty string when session_id is None", ctx == "", f"len={len(ctx)}")
    ctx = agent_mod._build_session_context_block("brand-new-session", exclude_run_id="x")
    passed &= _ok("empty string when session has no runs", ctx == "", f"len={len(ctx)}")
    return passed


def _phase_investigator_prompt_has_guidance() -> bool:
    print("── phase 5: investigator prompt mentions warm-start handling ──")
    prompt_path = Path(__file__).resolve().parent.parent / "server" / "prompts" / "investigator.md"
    txt = prompt_path.read_text(encoding="utf-8")
    passed = True
    passed &= _ok(
        "prompt references '## Partial progress'",
        "## Partial progress" in txt,
    )
    passed &= _ok(
        "prompt says 'Do not repeat checks'",
        "Do not repeat checks" in txt,
    )
    passed &= _ok(
        "prompt says 'Do not regenerate the same hypothesis set'",
        "Do not regenerate" in txt,
    )
    return passed


def main() -> int:
    # Preserve the process-wide store so we can restore it afterwards.
    saved_store = runs_module._STORE
    store, tmp = _install_temp_store()
    try:
        p1 = _phase_partial_progress_summary(store)
        print()
        p2 = _phase_warm_start_block_on_aborted(store)
        print()
        p3 = _phase_no_warm_start_on_success(store)
        print()
        p4 = _phase_no_context_without_session(store)
        print()
        p5 = _phase_investigator_prompt_has_guidance()
        print()
        if p1 and p2 and p3 and p4 and p5:
            print("WARM-START SMOKE PASS")
            return 0
        print("WARM-START SMOKE FAIL")
        return 1
    finally:
        _teardown(tmp, saved_store)


if __name__ == "__main__":
    sys.exit(main())
