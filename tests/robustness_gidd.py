"""Robustness test against a hard 2025 paper: GIDD / Scaling Behavior of
Discrete Diffusion Language Models (arXiv 2512.10858, Dec 2025).

This probe is deliberately picked to stress our system:
  - Paper is post-training-cutoff and in an unfamiliar domain (discrete
    diffusion LMs on TPU / JAX).
  - Repo is notebook-heavy (98% .ipynb, 1.7% .py).
  - Full reproduction requires TPU-scale compute (not feasible locally).
  - We want to verify the agent gracefully static-inspects and honestly
    reports what it can and cannot answer.

All Quick Checks run in read-only mode. Outputs are saved to
`test_data/real_papers/gidd/` for re-inspection.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from server.agent import RunConfig, run_agent
from server.env import load_env
from server.papers import ingest

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "test_data" / "real_papers" / "gidd"
OUT_DIR.mkdir(parents=True, exist_ok=True)

ARXIV_URL = "https://arxiv.org/abs/2512.10858"
REPO_URL = "https://github.com/dvruette/gidd-easydel.git"
REPO_DIR = Path("/tmp/real-gidd")


QUESTIONS = [
    "Is the codebase structured so CPU-only or single-GPU inference is feasible, or is it fundamentally tied to TPU / JAX distributed training? Cite the dependency declarations or hardware-specific code paths.",
    "Does the repo provide hyperparameter sweeps or scaling recipes for each model size (25M / 85M / 170M / 302M / 567M / 3B / 10B), or must the user hand-tune for each scale?",
    "Are pretrained model checkpoints published externally (HuggingFace or similar) so inference-only evaluation is feasible without a full training run? Cite the reference if any.",
    "Is the training data (Nemotron-CC) pinned to a specific version / preprocessing recipe in the repo, or does the code assume the user reproduces the data pipeline independently?",
    "Does the repo expose the interpolation parameter between masked and uniform diffusion (the paper's main methodological novelty) as a first-class configurable in the training config?",
]


@dataclass
class QuickCheckResult:
    question: str
    verdict: str | None = None
    confidence: float | None = None
    evidence: list = field(default_factory=list)
    notes: str | None = None
    tool_calls: int = 0
    duration_s: float = 0.0
    cost_usd: float = 0.0
    crashed: bool = False
    error: str | None = None


async def _ingest_and_save() -> dict:
    print("── ingesting paper ──")
    t0 = time.monotonic()
    paper = await ingest(ARXIV_URL)
    dt = time.monotonic() - t0
    print(f"  title: {paper.title!r}")
    print(f"  authors[:3]: {paper.authors[:3]}")
    print(f"  arxiv_id: {paper.arxiv_id}")
    print(f"  sections: {len(paper.sections)}")
    print(f"  markdown chars: {len(paper.full_markdown)}")
    print(f"  duration: {dt:.2f}s")

    # Save paper artifacts
    (OUT_DIR / "paper_meta.json").write_text(json.dumps({
        "source_url": paper.source_url,
        "source_type": paper.source_type,
        "arxiv_id": paper.arxiv_id,
        "title": paper.title,
        "authors": paper.authors,
        "abstract": paper.abstract,
        "sections_count": len(paper.sections),
        "markdown_chars": len(paper.full_markdown),
        "ingest_duration_s": round(dt, 2),
        "ingested_at": paper.ingested_at,
    }, indent=2))
    (OUT_DIR / "paper_full.md").write_text(paper.full_markdown)
    print(f"  saved paper_meta.json + paper_full.md to {OUT_DIR}")

    return {
        "title": paper.title,
        "authors": paper.authors[:3],
        "arxiv_id": paper.arxiv_id,
        "markdown_chars": len(paper.full_markdown),
        "sections": len(paper.sections),
        "ingest_duration_s": round(dt, 2),
    }


def _clone_repo() -> dict:
    print()
    print(f"── cloning {REPO_URL} ──")
    if REPO_DIR.exists():
        shutil.rmtree(REPO_DIR)
    t0 = time.monotonic()
    result = subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(REPO_DIR)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr}")
    dt = time.monotonic() - t0
    py_files = list(REPO_DIR.rglob("*.py"))
    ipynb_files = list(REPO_DIR.rglob("*.ipynb"))
    clone_size_bytes = sum(f.stat().st_size for f in REPO_DIR.rglob("*") if f.is_file())
    print(f"  clone duration: {dt:.2f}s")
    print(f"  .py files: {len(py_files)}, .ipynb files: {len(ipynb_files)}")
    print(f"  clone size: {clone_size_bytes/1024/1024:.1f} MB")
    return {
        "clone_duration_s": round(dt, 2),
        "py_file_count": len(py_files),
        "ipynb_file_count": len(ipynb_files),
        "clone_size_mb": round(clone_size_bytes / 1024 / 1024, 2),
    }


async def _quick_check(question: str) -> QuickCheckResult:
    result = QuickCheckResult(question=question)
    config = RunConfig.from_dict(
        mode="check",
        run_id=f"gidd-{int(time.time()*1000)}",
        raw={
            "repo_path": str(REPO_DIR),
            "question": question,
            "max_budget_usd": 2.0,  # slightly larger; repo is notebook-heavy
        },
    )
    t0 = time.monotonic()
    async for ev in run_agent(config):
        if ev["type"] == "tool_call":
            result.tool_calls += 1
        elif ev["type"] == "quick_check_verdict":
            d = ev["data"]
            result.verdict = d.get("verdict")
            result.confidence = d.get("confidence")
            result.evidence = d.get("evidence") or []
            result.notes = d.get("notes")
        elif ev["type"] == "error":
            result.crashed = True
            result.error = ev["data"].get("message", "unknown")
        elif ev["type"] == "session_end":
            result.cost_usd = float(ev["data"].get("cost_usd", 0.0))
            break
    result.duration_s = round(time.monotonic() - t0, 2)
    return result


async def main() -> int:
    load_env()
    paper_info = await _ingest_and_save()
    repo_info = _clone_repo()

    print()
    print("── running Quick Checks ──")
    checks: list[QuickCheckResult] = []
    total_cost = 0.0
    for i, q in enumerate(QUESTIONS, 1):
        print(f"\n  Q{i}: {q[:110]}{'…' if len(q) > 110 else ''}")
        r = await _quick_check(q)
        checks.append(r)
        total_cost += r.cost_usd
        if r.crashed:
            print(f"    ✗ CRASH: {r.error}")
            continue
        if r.verdict is None:
            print(f"    ✗ no verdict ({r.tool_calls} turns, {r.duration_s}s)")
            continue
        print(f"    ✓ verdict={r.verdict!r} conf={r.confidence} "
              f"evidence={len(r.evidence)} turns={r.tool_calls} "
              f"dur={r.duration_s}s cost=${r.cost_usd:.4f}")
        print(f"      notes: {(r.notes or '')[:180]}")

    # Save everything
    summary = {
        "paper": paper_info,
        "repo": {"url": REPO_URL, **repo_info},
        "checks": [asdict(c) for c in checks],
        "total_cost_usd": round(total_cost, 4),
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC",
    }
    (OUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (OUT_DIR / "questions.txt").write_text("\n\n".join(QUESTIONS))
    print()
    print(f"── saved test data to {OUT_DIR} ──")
    for f in sorted(OUT_DIR.iterdir()):
        size = f.stat().st_size if f.is_file() else sum(x.stat().st_size for x in f.rglob("*") if x.is_file())
        print(f"  {f.name}  ({size:,} bytes)")

    print()
    print(f"total cost: ${total_cost:.4f}")
    print()
    print("(this probe is deliberately a stress test; verdicts reflect what")
    print(" the agent could determine from static inspection — the repo is")
    print(" not locally runnable, so metric-delta flows are out of scope.)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
