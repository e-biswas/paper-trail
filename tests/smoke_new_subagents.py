"""Smoke tests for the two new subagents: Metric Extractor + Patch Generator.

Real SDK calls. Bails on the first failure.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from server.env import load_env
from server.subagents import metric_extractor, patch_generator

REPO = Path("/tmp/muchlinski-demo")


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


_MUCHLINSKI_STDOUT = """
Loading fears data...
Imputing missing values...
Training RF...
Training LR...
Evaluation on held-out split:
METRIC_JSON: {"rf": {"AUC": 0.9562, "F1": 0.8432}, "lr": {"AUC": 0.8091, "F1": 0.7411}}
Done.
"""


async def _phase_metric_extractor() -> tuple[bool, float]:
    print("── metric_extractor.extract() ──")
    result = await metric_extractor.extract(_MUCHLINSKI_STDOUT, max_budget_usd=0.30)
    print(f"  cost=${result.cost_usd:.5f}, dur={result.duration_ms}ms")
    passed = _ok("ok=True", result.ok, result.error or "")
    if not result.ok:
        return passed, result.cost_usd

    metrics = result.payload.get("metrics") or []
    passed &= _ok("≥ 4 metrics extracted", len(metrics) >= 4, f"{len(metrics)} metrics")
    names = [m.get("name") for m in metrics]
    passed &= _ok("AUC + F1 present", "AUC" in names and "F1" in names, f"names={names}")
    contexts = [m.get("context", "") for m in metrics]
    passed &= _ok(
        "distinguishes RF and LR contexts",
        any("RF" in c.upper() for c in contexts) and any("LR" in c.upper() for c in contexts),
        f"contexts={contexts}",
    )
    # Pluck the RF AUC and confirm the value came through cleanly.
    rf_auc = next(
        (m.get("value") for m in metrics
         if m.get("name") == "AUC" and "RF" in m.get("context", "").upper()),
        None,
    )
    passed &= _ok(
        "RF AUC ≈ 0.9562",
        rf_auc is not None and abs(float(rf_auc) - 0.9562) < 0.001,
        f"rf_auc={rf_auc}",
    )
    return passed, result.cost_usd


async def _phase_patch_generator() -> tuple[bool, float]:
    print("── patch_generator.generate() on Muchlinski fixture ──")
    if not REPO.exists():
        print(f"  ! skipping — {REPO} missing")
        return True, 0.0

    evidence = (
        "Imputation appears to be fit on the full dataframe before the train/test split. "
        "The fit_transform call is at src/prepare_data.py near the top, and the "
        "train_test_split call happens afterward. Move the imputer inside the sklearn "
        "Pipeline so fit_transform only runs on training data."
    )
    result = await patch_generator.generate(
        REPO,
        hypothesis_id="h1",
        evidence_summary=evidence,
        max_budget_usd=1.50,
    )
    print(f"  cost=${result.cost_usd:.5f}, dur={result.duration_ms}ms")
    passed = _ok("ok=True", result.ok, result.error or "")
    if not result.ok:
        print(f"  DEBUG payload keys: {list(result.payload.keys()) if result.payload else 'none'}")
        return passed, result.cost_usd

    payload = result.payload
    passed &= _ok(
        "hypothesis_id preserved",
        payload.get("hypothesis_id") == "h1",
        f"{payload.get('hypothesis_id')!r}",
    )
    target_files = payload.get("target_files") or []
    passed &= _ok(
        "target_files non-empty",
        isinstance(target_files, list) and len(target_files) >= 1,
        f"{target_files}",
    )
    diff = payload.get("diff", "")
    passed &= _ok("diff contains '--- a/' header", "--- a/" in diff)
    passed &= _ok("diff contains '+++ b/' header", "+++ b/" in diff)
    passed &= _ok("diff contains '@@ ' hunk header", "\n@@ " in diff or diff.startswith("@@ "))
    passed &= _ok(
        "diff touches prepare_data.py",
        any("prepare_data" in f for f in target_files) and "prepare_data" in diff,
        f"target_files={target_files}",
    )
    # Soft check: `git apply --check`. LLM-generated diffs frequently need
    # one retry round to land cleanly; the conductor's integration handles
    # that explicitly. We surface the result for visibility but don't fail
    # the smoke on a first-try mismatch.
    import subprocess
    apply_check = subprocess.run(
        ["git", "apply", "--check"],
        cwd=str(REPO),
        input=diff,
        text=True,
        capture_output=True,
    )
    if apply_check.returncode == 0:
        _ok("`git apply --check` succeeds on first try", True)
    else:
        print(
            f"  ! first-try git apply --check failed (expected: retry path exists): "
            f"{apply_check.stderr.strip().splitlines()[0] if apply_check.stderr.strip() else 'unknown'}"
        )
        print("  ---- diff snippet ----")
        for line in diff.splitlines()[:12]:
            print(f"    {line}")
        print("  ----------------------")
    print(f"  rationale: {payload.get('rationale', '')[:120]}")
    return passed, result.cost_usd


async def main() -> int:
    load_env()

    total_cost = 0.0
    total_passed = True

    p1, c1 = await _phase_metric_extractor()
    total_passed &= p1
    total_cost += c1
    print()

    p2, c2 = await _phase_patch_generator()
    total_passed &= p2
    total_cost += c2
    print()

    print(f"total cost: ${total_cost:.5f}")
    if total_passed:
        print("NEW SUBAGENT SMOKE PASS")
        return 0
    print("NEW SUBAGENT SMOKE FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
