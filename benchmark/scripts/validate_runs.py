"""Run the Validator subagent over every completed Deep Investigation in the
benchmark and persist a `validity_report.json` next to each run's artifacts.

Quick Check runs are not validated — the Validator prompt is written for the
investigator contract (hypothesis coverage, fix minimality, causal link, etc.)
and does not meaningfully apply to a bounded verification question. The
benchmark's consistency analysis evaluates Quick Check quality directly from
verdict labels and evidence citations, which are the quality signal for that
mode.

Resumable: existing validity_report.json files are skipped unless --force.

Usage:
  uv run python benchmark/scripts/validate_runs.py
  uv run python benchmark/scripts/validate_runs.py --force
  uv run python benchmark/scripts/validate_runs.py --paper tabm
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from server.env import load_env  # noqa: E402
from server.papers import ingest  # noqa: E402
from server.subagents import validator  # noqa: E402

BENCH_ROOT = ROOT / "benchmark"
RUNS_DIR = BENCH_ROOT / "runs"


def _iter_deep_run_dirs(paper_filter: str | None) -> list[Path]:
    dirs: list[Path] = []
    for paper_dir in sorted(RUNS_DIR.iterdir() if RUNS_DIR.exists() else []):
        if not paper_dir.is_dir():
            continue
        if paper_filter and paper_dir.name != paper_filter:
            continue
        deep_dir = paper_dir / "investigate"
        if not deep_dir.exists():
            continue
        for q_dir in sorted(deep_dir.iterdir()):
            for repeat_dir in sorted(q_dir.iterdir()):
                if (repeat_dir / "run_meta.json").exists():
                    dirs.append(repeat_dir)
    return dirs


def _reconstruct_transcript(events_jsonl: Path) -> str:
    """Build a Validator-friendly transcript from persisted envelope events.

    Mirrors the mapping in `server/main.py::validate_run`. Keeping it here
    avoids a dependency on a running server.
    """
    parts: list[str] = []
    with events_jsonl.open() as f:
        for line in f:
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = ev.get("type")
            data = ev.get("data") or {}
            if etype == "claim_summary":
                parts.append(f"## Claim:\nclaim: {data.get('claim', '')!r}\n")
            elif etype == "hypothesis":
                parts.append(
                    f"## Hypothesis {data.get('rank', '?')}: {data.get('name', '')}\n"
                    f"id: {data.get('id')}\n"
                    f"confidence: {data.get('confidence')}\n"
                    f"reason: {data.get('reason', '')!r}\n"
                )
            elif etype == "hypothesis_update":
                parts.append(
                    f"## Hypothesis update ({data.get('id')}):\n"
                    f"confidence: {data.get('confidence')}\n"
                    f"reason_delta: {data.get('reason_delta', '')!r}\n"
                )
            elif etype == "check":
                parts.append(
                    f"## Check: {data.get('id')}\n"
                    f"hypothesis_id: {data.get('hypothesis_id')}\n"
                    f"description: {data.get('description', '')!r}\n"
                    f"method: {data.get('method', '')!r}\n"
                )
            elif etype == "finding":
                parts.append(
                    f"## Finding: {data.get('id')}\n"
                    f"check_id: {data.get('check_id')}\n"
                    f"result: {data.get('result', '')!r}\n"
                    f"supports: {data.get('supports', [])}\n"
                    f"refutes: {data.get('refutes', [])}\n"
                )
            elif etype == "verdict":
                parts.append(
                    f"## Verdict:\n"
                    f"hypothesis_id: {data.get('hypothesis_id')}\n"
                    f"confidence: {data.get('confidence')}\n"
                    f"summary: {data.get('summary', '')!r}\n"
                )
            elif etype == "fix_applied":
                parts.append(
                    f"## Fix applied:\n"
                    f"files_changed: {data.get('files_changed', [])}\n"
                    f"diff_summary: {data.get('diff_summary', '')!r}\n"
                )
            elif etype == "metric_delta":
                parts.append(
                    f"## Metric delta:\n"
                    f"metric: {data.get('metric', '')!r}\n"
                    f"before: {data.get('before')}\n"
                    f"after: {data.get('after')}\n"
                    f"context: {data.get('context', '')!r}\n"
                )
            elif etype == "dossier_section":
                parts.append(
                    f"## Dossier — {(data.get('section') or '').replace('_', ' ')}:\n"
                    f"{data.get('markdown', '')}\n"
                )
    return "\n".join(parts).strip()


async def _load_paper_context(paper_url: str) -> str:
    try:
        paper = await ingest(paper_url)
        body = paper.full_markdown
        if len(body) > 15_000:
            body = body[:15_000] + f"\n\n[... truncated; original was {len(paper.full_markdown)} chars ...]"
        return body
    except Exception as exc:
        return f"(paper ingest failed: {exc})"


def _compute_diff(repo_clone: Path) -> str | None:
    if not repo_clone.exists() or not (repo_clone / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_clone), "diff", "--patch"],
            check=False, capture_output=True, text=True, timeout=20,
        )
        if out.returncode != 0:
            return None
        diff = out.stdout or ""
        return diff if diff.strip() else None
    except Exception:
        return None


async def _validate_one(run_dir: Path, *, force: bool) -> dict[str, Any] | None:
    report_path = run_dir / "validity_report.json"
    if report_path.exists() and not force:
        return None

    meta = json.loads((run_dir / "run_meta.json").read_text())
    if not meta.get("reached_session_end"):
        # Skip broken runs — the transcript is probably too thin to audit.
        return {"skipped": "run did not reach session_end", "run_id": meta.get("run_id")}

    events_path = run_dir / "events.jsonl"
    transcript = _reconstruct_transcript(events_path)
    if not transcript or len(transcript) < 100:
        return {"skipped": "transcript too short", "run_id": meta.get("run_id")}

    paper_context = await _load_paper_context(meta.get("paper_url") or "")
    diff_text = _compute_diff(Path(meta.get("repo_clone")))

    config_summary = (
        f"mode: {meta.get('mode')}\n"
        f"repo_path: {meta.get('repo_clone')}\n"
        f"paper_url: {meta.get('paper_url')}\n"
        f"repo_slug: {meta.get('repo_slug')}\n"
        f"stop_reason: {meta.get('stop_reason')}\n"
        f"cost_usd: {meta.get('cost_usd')}\n"
        f"total_turns: {meta.get('total_turns')}\n"
        f"tool_calls: {meta.get('tool_calls')}\n"
    )

    t0 = time.monotonic()
    result = await validator.validate(
        paper_context=paper_context,
        run_transcript=transcript,
        run_config_summary=config_summary,
        diff_text=diff_text,
    )
    elapsed = time.monotonic() - t0

    out: dict[str, Any] = {
        "run_id": meta.get("run_id"),
        "ok": result.ok,
        "summary": result.summary,
        "error": result.error,
        "cost_usd": result.cost_usd,
        "duration_ms": result.duration_ms or int(elapsed * 1000),
        "payload": result.payload,
    }
    report_path.write_text(json.dumps(out, indent=2))
    return out


async def _main(args: argparse.Namespace) -> None:
    load_env()
    run_dirs = _iter_deep_run_dirs(args.paper)
    print(f"[validator] Found {len(run_dirs)} Deep Investigation run dirs "
          f"(paper filter: {args.paper or 'all'}).")

    total_cost = 0.0
    processed = 0
    skipped = 0
    for run_dir in run_dirs:
        out = await _validate_one(run_dir, force=args.force)
        if out is None:
            skipped += 1
            print(f"[validator] skip {run_dir.relative_to(RUNS_DIR)} (already validated)")
            continue
        if "skipped" in out:
            skipped += 1
            print(f"[validator] skip {run_dir.relative_to(RUNS_DIR)}: {out['skipped']}")
            continue
        total_cost += float(out.get("cost_usd") or 0.0)
        processed += 1
        payload = out.get("payload") or {}
        overall = payload.get("overall")
        n_checks = len(payload.get("checks") or [])
        print(f"[validator] done {run_dir.relative_to(RUNS_DIR)}: overall={overall} "
              f"checks={n_checks} cost=${out.get('cost_usd'):.3f}")

    print(f"\n[validator] processed={processed} skipped={skipped} "
          f"session_cost=${total_cost:.2f}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--paper", choices=["gidd", "tabm"], help="restrict to one paper")
    p.add_argument("--force", action="store_true", help="re-validate runs even if a report exists")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
