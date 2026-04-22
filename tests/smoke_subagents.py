"""Subagent smoke tests.

Exercises all three Day-2 subagents against the staged Muchlinski fixture at
/tmp/muchlinski-demo. Real SDK calls — non-trivial cost. Bail if any fails.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from server.env import load_env
from server.subagents import code_auditor, experiment_runner, paper_reader

REPO = Path("/tmp/muchlinski-demo")
PAPER_MD = Path("test_data/papers/muchlinski.md")


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    print(f"  {icon} {label}{' — ' + detail if detail else ''}")
    return predicate


async def main() -> int:
    load_env()
    if not REPO.exists():
        print(f"FAIL: /tmp/muchlinski-demo missing — run demo/primary/stage.sh first")
        return 1
    if not PAPER_MD.exists():
        print(f"FAIL: {PAPER_MD} missing")
        return 1

    total_cost = 0.0
    passed = True

    # ── paper_reader ───────────────────────────────────────────────────
    print("── paper_reader.summarize() ──")
    pr_result = await paper_reader.summarize(PAPER_MD.read_text(), max_budget_usd=0.50)
    total_cost += pr_result.cost_usd
    passed &= _ok("ok=True", pr_result.ok, f"cost=${pr_result.cost_usd:.5f}, dur={pr_result.duration_ms}ms")
    passed &= _ok("primary_claim mentions 'Random Forest' or 'RF'",
                  "Random Forest" in pr_result.summary or " RF " in pr_result.summary)
    passed &= _ok("payload has commitments list with real entries",
                  isinstance(pr_result.payload.get("commitments"), list)
                  and len(pr_result.payload["commitments"]) > 0
                  and any(c for c in pr_result.payload["commitments"] if c))
    print(f"  primary_claim: {pr_result.summary[:120]}…" if len(pr_result.summary) > 120 else f"  primary_claim: {pr_result.summary}")
    print()

    # ── code_auditor ───────────────────────────────────────────────────
    print("── code_auditor.audit() ──")
    q = "Is the imputer fit on the full dataframe, or on training data only?"
    ca_result = await code_auditor.audit(
        REPO,
        q,
        hints=["src/prepare_data.py"],
        max_budget_usd=1.00,
    )
    total_cost += ca_result.cost_usd
    passed &= _ok("ok=True", ca_result.ok, f"cost=${ca_result.cost_usd:.5f}, dur={ca_result.duration_ms}ms")
    passed &= _ok(
        "summary references full-df / unsplit imputation",
        any(k in ca_result.summary.lower() for k in ["full", "entire", "whole", "before", "prior", "fit_transform(df"]),
    )
    evidence = ca_result.payload.get("evidence") or []
    passed &= _ok("evidence has at least one entry", len(evidence) >= 1, f"{len(evidence)} entries")
    if evidence:
        prepare_lines = [e for e in evidence if isinstance(e, dict) and "prepare_data" in str(e.get("file", ""))]
        passed &= _ok("at least one evidence entry points at prepare_data.py", len(prepare_lines) >= 1)
    print(f"  summary: {ca_result.summary}")
    print()

    # ── experiment_runner ─────────────────────────────────────────────
    print("── experiment_runner.run() ──")
    er_result = await experiment_runner.run(
        REPO,
        "python src/eval.py",
        max_budget_usd=1.00,
    )
    total_cost += er_result.cost_usd
    passed &= _ok("ok=True", er_result.ok, f"cost=${er_result.cost_usd:.5f}, dur={er_result.duration_ms}ms")
    if not er_result.ok:
        print(f"  DEBUG raw payload: {json.dumps(er_result.payload, indent=2, default=str)[:1000]}")
        if er_result.error:
            print(f"  DEBUG error: {er_result.error[:500]}")
    metric_json = er_result.payload.get("metric_json") or {}
    # If the parser returned it as a string (inline JSON in a scalar value),
    # try to decode it explicitly.
    if isinstance(metric_json, str):
        try:
            metric_json = json.loads(metric_json)
        except json.JSONDecodeError:
            metric_json = {}
    passed &= _ok(
        "metric_json populated",
        isinstance(metric_json, dict) and bool(metric_json),
        f"keys={list(metric_json.keys()) if isinstance(metric_json, dict) else type(metric_json).__name__}",
    )
    # The Muchlinski fixture's broken eval prints rf≈0.9562, lr≈0.8091
    rf_val = None
    if isinstance(metric_json, dict):
        for key in ("rf", "RF", "AUC_RF"):
            if key in metric_json:
                rf_val = metric_json[key]
                break
    if rf_val is not None:
        passed &= _ok("RF AUC matches ground truth (≈0.9562)",
                      abs(float(rf_val) - 0.9562) < 0.01, f"rf={rf_val}")
    print(f"  summary: {er_result.summary}")
    print()

    # ── verdict ────────────────────────────────────────────────────────
    print("── verdict ──")
    print(f"  total cost: ${total_cost:.5f}")
    if passed:
        print("  ALL SUBAGENT SMOKES PASSED")
        return 0
    print("  SMOKE FAIL — see above")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
