"""Paper-Trail consistency benchmark runner.

Runs each (paper, question, mode) triple N times via the core `run_agent`
orchestrator with `auto_pr=False`. Artifacts land under
`benchmark/runs/<paper>/<mode>/<question_id>/repeat_<k>/` so re-runs can
resume without double-billing.

Design notes:
- Quick Check repeats share a single read-only clone per paper. Deep
  Investigation repeats each get a fresh clone (the agent edits files).
- A hard TOTAL_BUDGET_USD cap aborts the run before starting any invocation
  that would exceed it. The running spend is rebuilt from persisted
  run_meta.json files on every start, so interrupted runs resume safely.
- Paper ingestion is handled by the core system (cached on disk).

Usage:
  uv run python benchmark/scripts/run_benchmark.py --smoke       # 1 repeat, tabm only
  uv run python benchmark/scripts/run_benchmark.py               # full: 3 repeats, both papers
  uv run python benchmark/scripts/run_benchmark.py --paper gidd  # one paper only
  uv run python benchmark/scripts/run_benchmark.py --mode check  # quick checks only
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from server.agent import RunConfig, run_agent  # noqa: E402
from server.env import load_env  # noqa: E402

BENCH_ROOT = ROOT / "benchmark"
QUESTIONS_DIR = BENCH_ROOT / "questions"
RUNS_DIR = BENCH_ROOT / "runs"

TOTAL_BUDGET_USD = 45.0
PER_QUICK_CHECK_BUDGET_USD = 0.50
PER_DEEP_BUDGET_USD = 2.50


@dataclass
class RunTask:
    paper: str
    mode: str              # "check" or "investigate"
    question_id: str
    question_text: str
    paper_url: str
    repo_slug: str
    repo_clone: Path       # fresh per-Deep-repeat; shared for Quick Check
    out_dir: Path          # artifacts dir for this (paper, mode, q_id, repeat)
    repeat_idx: int        # 0-based

    @property
    def budget_usd(self) -> float:
        return PER_DEEP_BUDGET_USD if self.mode == "investigate" else PER_QUICK_CHECK_BUDGET_USD

    @property
    def is_complete(self) -> bool:
        meta_path = self.out_dir / "run_meta.json"
        if not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            return False
        # Completed = we reached session_end for any reason (ok=True or a
        # terminal stop_reason like turn_cap). Only treat crashed / empty as
        # incomplete so we actually retry those.
        return bool(meta.get("reached_session_end"))


def _load_target(name: str) -> dict[str, Any]:
    return json.loads((QUESTIONS_DIR / f"{name}.json").read_text())


def _ensure_clone(repo_url: str, dest: Path, *, fresh: bool = False) -> None:
    """Shallow-clone `repo_url` into `dest`. If `fresh`, wipe any existing dir."""
    if fresh and dest.exists():
        shutil.rmtree(dest)
    if dest.exists() and (dest / ".git").exists():
        return  # already cloned
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", "--depth=1", repo_url, str(dest)],
        check=True,
        capture_output=True,
    )


def _spent_so_far() -> float:
    total = 0.0
    for meta_path in RUNS_DIR.rglob("run_meta.json"):
        try:
            meta = json.loads(meta_path.read_text())
            total += float(meta.get("cost_usd") or 0.0)
        except Exception:
            continue
    return total


def _build_task_list(
    targets: list[str], repeats: int, mode_filter: str | None
) -> list[RunTask]:
    tasks: list[RunTask] = []
    for tname in targets:
        target = _load_target(tname)
        clone_root = Path(target["local_clone_root"])
        # Quick Check
        if mode_filter in (None, "check"):
            qc_clone = clone_root.with_name(clone_root.name + "-check")
            for qc in target["quick_checks"]:
                for k in range(repeats):
                    tasks.append(RunTask(
                        paper=tname,
                        mode="check",
                        question_id=qc["id"],
                        question_text=qc["question"],
                        paper_url=target["paper_url"],
                        repo_slug=target["repo_slug"],
                        repo_clone=qc_clone,
                        out_dir=RUNS_DIR / tname / "check" / qc["id"] / f"repeat_{k}",
                        repeat_idx=k,
                    ))
        # Deep Investigation
        if mode_filter in (None, "investigate"):
            deep = target["deep_investigation"]
            for k in range(repeats):
                per_clone = clone_root.with_name(f"{clone_root.name}-deep-{k}")
                tasks.append(RunTask(
                    paper=tname,
                    mode="investigate",
                    question_id=deep["id"],
                    question_text=deep["prompt"],
                    paper_url=target["paper_url"],
                    repo_slug=target["repo_slug"],
                    repo_clone=per_clone,
                    out_dir=RUNS_DIR / tname / "investigate" / deep["id"] / f"repeat_{k}",
                    repeat_idx=k,
                ))
    return tasks


async def _execute_task(task: RunTask) -> dict[str, Any]:
    """Run one invocation. Persists events.jsonl + run_meta.json into task.out_dir."""
    task.out_dir.mkdir(parents=True, exist_ok=True)

    # Clone handling — Quick Check clone is shared & read-only; Deep gets fresh.
    fresh = (task.mode == "investigate")
    _ensure_clone(_target_repo_url(task.paper), task.repo_clone, fresh=fresh)

    run_id = f"bench-{task.paper}-{task.mode}-{task.question_id}-r{task.repeat_idx}-{uuid.uuid4().hex[:8]}"

    raw_cfg: dict[str, Any] = {
        "repo_path": str(task.repo_clone),
        "paper_url": task.paper_url,
        "repo_slug": task.repo_slug,
        "auto_pr": False,
        "max_budget_usd": task.budget_usd,
    }
    if task.mode == "check":
        raw_cfg["question"] = task.question_text
    else:
        # The investigator prompt expects open-ended; we splice the professor
        # prompt as the user's guiding question through extras.user_prompt.
        # But `run_agent` only uses user_prompt when it's in `extras`; see
        # server.agent.RunConfig.from_dict. For Deep we also want the prompt
        # passed to the conductor — so we include it via extras.user_prompt
        # and rely on the investigator system prompt to treat it as the brief.
        raw_cfg["user_prompt"] = task.question_text

    config = RunConfig.from_dict(mode=task.mode, run_id=run_id, raw=raw_cfg)  # type: ignore[arg-type]

    events_path = task.out_dir / "events.jsonl"
    meta_path = task.out_dir / "run_meta.json"

    started = time.monotonic()
    reached_end = False
    session_end_data: dict[str, Any] | None = None
    hypotheses: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    qc_verdict: dict[str, Any] | None = None
    fix_applied: dict[str, Any] | None = None
    metric_deltas: list[dict[str, Any]] = []
    dossier_sections: dict[str, str] = {}
    tool_calls = 0
    claim_summary: str | None = None

    with events_path.open("w") as ef:
        try:
            async for event in run_agent(config):
                ef.write(json.dumps(event) + "\n")
                etype = event.get("type")
                data = event.get("data", {})
                if etype == "hypothesis":
                    hypotheses.append({"id": data.get("id"), "name": data.get("name"),
                                       "confidence": data.get("confidence"),
                                       "rank": data.get("rank")})
                elif etype == "verdict":
                    verdicts.append({"hypothesis_id": data.get("hypothesis_id"),
                                     "confidence": data.get("confidence"),
                                     "summary": data.get("summary")})
                elif etype == "quick_check_verdict":
                    qc_verdict = {
                        "verdict": data.get("verdict"),
                        "confidence": data.get("confidence"),
                        "evidence": data.get("evidence", []),
                        "notes": data.get("notes"),
                    }
                elif etype == "fix_applied":
                    fix_applied = {
                        "files_changed": data.get("files_changed", []),
                        "diff_summary": data.get("diff_summary"),
                    }
                elif etype == "metric_delta":
                    metric_deltas.append({
                        "metric": data.get("metric"),
                        "before": data.get("before"),
                        "after": data.get("after"),
                        "context": data.get("context"),
                    })
                elif etype == "dossier_section":
                    dossier_sections[data.get("section", "unknown")] = data.get("markdown", "")
                elif etype == "claim_summary":
                    claim_summary = data.get("claim")
                elif etype == "tool_call":
                    tool_calls += 1
                elif etype == "session_end":
                    session_end_data = data
                    reached_end = True
        except Exception as exc:
            # Record and move on; make_report will flag these.
            meta_path.write_text(json.dumps({
                "run_id": run_id,
                "paper": task.paper,
                "mode": task.mode,
                "question_id": task.question_id,
                "repeat_idx": task.repeat_idx,
                "reached_session_end": False,
                "error": f"{type(exc).__name__}: {exc}",
                "duration_s": time.monotonic() - started,
            }, indent=2))
            return {"run_id": run_id, "error": str(exc), "cost_usd": 0.0}

    meta = {
        "run_id": run_id,
        "paper": task.paper,
        "mode": task.mode,
        "question_id": task.question_id,
        "question_text": task.question_text,
        "repeat_idx": task.repeat_idx,
        "paper_url": task.paper_url,
        "repo_slug": task.repo_slug,
        "repo_clone": str(task.repo_clone),
        "reached_session_end": reached_end,
        "ok": bool(session_end_data and session_end_data.get("ok")),
        "stop_reason": (session_end_data or {}).get("stop_reason"),
        "cost_usd": float((session_end_data or {}).get("cost_usd") or 0.0),
        "duration_ms": int((session_end_data or {}).get("duration_ms") or 0),
        "total_turns": int((session_end_data or {}).get("total_turns") or 0),
        "tool_calls": tool_calls,
        "claim_summary": claim_summary,
        "hypotheses": hypotheses,
        "verdicts": verdicts,
        "quick_check_verdict": qc_verdict,
        "fix_applied": fix_applied,
        "metric_deltas": metric_deltas,
        "dossier_section_keys": sorted(dossier_sections.keys()),
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    # Also dump the dossier for human inspection.
    if dossier_sections:
        (task.out_dir / "dossier.md").write_text(
            "\n\n".join(f"## {k}\n\n{v}" for k, v in dossier_sections.items())
        )

    return meta


def _target_repo_url(paper: str) -> str:
    return _load_target(paper)["repo_url"]


async def _main(args: argparse.Namespace) -> None:
    load_env()

    targets = [args.paper] if args.paper else ["gidd", "tabm"]
    repeats = 1 if args.smoke else args.repeats
    mode_filter = args.mode

    tasks = _build_task_list(targets, repeats, mode_filter)
    # Pending tasks only, unless --force
    pending = [t for t in tasks if args.force or not t.is_complete]

    already_spent = _spent_so_far()
    print(f"[bench] targets={targets} repeats={repeats} mode={mode_filter or 'both'}")
    print(f"[bench] {len(tasks)} total tasks, {len(pending)} pending")
    print(f"[bench] budget already spent (prior runs): ${already_spent:.2f}")
    print(f"[bench] total cap: ${TOTAL_BUDGET_USD:.2f}  — remaining: ${TOTAL_BUDGET_USD - already_spent:.2f}")
    if args.smoke:
        # Smoke = tabm only, 1 repeat, to keep cost ≈ $3
        pending = [t for t in pending if t.paper == "tabm"][:4]  # 3 QC + 1 Deep = 4
        print(f"[bench] SMOKE mode: pruned to {len(pending)} tasks (tabm only)")

    if args.dry_run:
        for t in pending:
            print(f"  - {t.paper}/{t.mode}/{t.question_id}/r{t.repeat_idx}  (~${t.budget_usd})")
        print(f"[bench] dry run — no API calls made. Est max spend on pending: "
              f"${sum(t.budget_usd for t in pending):.2f}")
        return

    executed: list[dict[str, Any]] = []
    spent_this_session = 0.0
    for i, task in enumerate(pending, 1):
        # Budget guard — reads live persisted spend every iteration.
        running_spend = already_spent + spent_this_session
        if running_spend + task.budget_usd > TOTAL_BUDGET_USD:
            print(f"[bench] STOP: next task ({task.paper}/{task.mode}/r{task.repeat_idx}) "
                  f"would push spend from ${running_spend:.2f} past cap ${TOTAL_BUDGET_USD:.2f}.")
            break

        label = f"[{i}/{len(pending)}] {task.paper}/{task.mode}/{task.question_id}/r{task.repeat_idx}"
        print(f"{label} — starting (budget ${task.budget_usd}, running spend ${running_spend:.2f})")

        t0 = time.monotonic()
        try:
            meta = await _execute_task(task)
        except Exception as exc:
            print(f"{label} !! exception: {exc}")
            continue

        cost = float(meta.get("cost_usd") or 0.0)
        spent_this_session += cost
        elapsed = time.monotonic() - t0
        stop_reason = meta.get("stop_reason") or ("ok" if meta.get("ok") else "unknown")
        print(f"{label} — done in {elapsed:.1f}s cost=${cost:.3f} stop={stop_reason}")
        executed.append(meta)

    total = already_spent + spent_this_session
    print(f"\n[bench] session complete. Ran {len(executed)} new tasks. "
          f"Session spend: ${spent_this_session:.2f}. Grand total: ${total:.2f}.")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--smoke", action="store_true", help="tabm only, 1 repeat, ≈$3 ceiling")
    p.add_argument("--repeats", type=int, default=3, help="repeats per question (default: 3)")
    p.add_argument("--paper", choices=["gidd", "tabm"], help="restrict to one paper")
    p.add_argument("--mode", choices=["check", "investigate"], help="restrict to one mode")
    p.add_argument("--force", action="store_true", help="re-run completed tasks")
    p.add_argument("--dry-run", action="store_true", help="list tasks; make no API calls")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
