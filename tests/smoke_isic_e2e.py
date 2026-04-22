"""End-to-end test — Deep Investigation on the ISIC backup fixture.

Proves the agent generalizes beyond the primary demo: same orchestrator,
different failure class (duplicate-image leakage instead of imputation).
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from server.agent import RunConfig, run_agent
from server.env import load_env

ROOT = Path(__file__).resolve().parent.parent
GROUND_TRUTH = ROOT / "test_data" / "ground_truth" / "isic.json"
PAPER_MD = ROOT / "test_data" / "papers" / "isic.md"
REPO_PATH = Path("/tmp/isic-demo")


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


def _reset_fixture() -> None:
    stage = ROOT / "demo" / "backup" / "stage.sh"
    subprocess.run(
        [str(stage)],
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ,
             "REPRO_DEMO_TARGET": str(REPO_PATH),
             "GITHUB_BOT_REPO": os.environ.get("GITHUB_BOT_REPO_ISIC", os.environ.get("GITHUB_BOT_REPO", ""))},
    )


async def main() -> int:
    load_env()
    gt = json.loads(GROUND_TRUTH.read_text())

    print("── prep ──")
    _reset_fixture()
    print(f"  reset fixture → {REPO_PATH}")

    gh_owner = os.environ.get("GITHUB_BOT_OWNER")
    gh_repo = os.environ.get("GITHUB_BOT_REPO_ISIC", os.environ.get("GITHUB_BOT_REPO"))
    repo_slug = f"{gh_owner}/{gh_repo}" if gh_owner and gh_repo else None
    print(f"  repo_slug: {repo_slug or '(not set — PR will be skipped)'}")

    config = RunConfig.from_dict(
        mode="investigate",
        run_id=f"e2e-isic-{int(time.time())}",
        raw={
            "repo_path": str(REPO_PATH),
            "paper_url": str(PAPER_MD),
            "repo_slug": repo_slug,
            "max_budget_usd": 6.0,
        },
    )

    print()
    print("── running Deep Investigation on ISIC ──")
    t0 = time.monotonic()
    events: list[dict[str, Any]] = []
    hypothesis_events: list[dict[str, Any]] = []
    verdict_event: dict[str, Any] | None = None
    metric_delta_events: list[dict[str, Any]] = []
    dossier_sections_seen: set[str] = set()

    async for ev in run_agent(config):
        events.append(ev)
        etype = ev["type"]
        data = ev.get("data", {})
        elapsed = time.monotonic() - t0
        print(f"  [{elapsed:6.1f}s] {etype:22s} "
              f"{str(data)[:90]}{'…' if len(str(data)) > 90 else ''}")

        if etype == "hypothesis":
            hypothesis_events.append(data)
        elif etype == "verdict":
            verdict_event = data
        elif etype == "metric_delta":
            metric_delta_events.append(data)
        elif etype == "dossier_section":
            dossier_sections_seen.add(data.get("section", ""))
        elif etype == "session_end":
            print(f"   total turns: {data.get('total_turns')}, cost: ${data.get('cost_usd'):.4f}")
            break

    # ── acceptance checks (from ground_truth/isic.json) ────────────────
    print()
    print("── acceptance checks ──")
    passed = True

    top2 = [h for h in hypothesis_events if h.get("rank") in (1, 2)]
    passed &= _ok(
        "top-2 hypothesis references duplicate / dedup",
        any(
            any(kw in (h.get("name") or "").lower()
                for kw in ("duplicat", "dedup", "hash", "leak"))
            for h in top2
        ),
        f"top-2 names: {[h.get('name') for h in top2]}",
    )

    passed &= _ok(
        "verdict confidence ≥ 0.80 (ISIC target slightly softer than Muchlinski)",
        bool(verdict_event) and float(verdict_event.get("confidence", 0.0)) >= 0.80,
        f"{verdict_event.get('confidence') if verdict_event else 'no verdict'}",
    )

    # AUC_RF drops by ≥ 0.04 after the dedup fix (ground_truth says 0.04 min)
    if metric_delta_events:
        drops = [float(m.get("before", 0)) - float(m.get("after", 0)) for m in metric_delta_events]
        passed &= _ok(
            "AUC drops ≥ 0.04 after fix",
            any(d >= 0.04 for d in drops),
            f"drops={[f'{d:.4f}' for d in drops]}",
        )
    else:
        passed &= _ok("metric_delta emitted", False, "no metric_delta events")

    canonical = {"claim_tested", "evidence_gathered", "root_cause", "fix_applied", "remaining_uncertainty"}
    missing = canonical - dossier_sections_seen
    passed &= _ok(
        "all 5 canonical dossier sections emitted",
        not missing,
        f"missing={sorted(missing)}" if missing else "all present",
    )

    if repo_slug:
        pr_events = [e for e in events if e["type"] == "pr_opened"]
        passed &= _ok(
            "pr_opened envelope emitted",
            len(pr_events) == 1,
        )
        if pr_events:
            print(f"  PR URL: {pr_events[0]['data'].get('url')}")

    run_duration_s = time.monotonic() - t0
    print()
    print(f"run duration: {run_duration_s:.1f}s ({len(events)} envelopes)")
    if passed:
        print("ISIC E2E PASS")
        return 0
    print("ISIC E2E FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
