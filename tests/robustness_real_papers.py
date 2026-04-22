"""Robustness probe against two real-world paper+repo pairs (FED + TabM).

Saves structured outputs to `test_data/real_papers/<target>/` so runs are
inspectable after the fact. Re-runs are idempotent; the paper ingester
uses its on-disk cache so the arXiv / docling work happens once.

Sister script: `tests/robustness_gidd.py` runs the harder 2025 target.
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
OUT_ROOT = ROOT / "test_data" / "real_papers"


@dataclass
class Target:
    name: str            # used as subdir name
    arxiv_url: str
    repo_url: str
    repo_dir: Path
    questions: list[str]
    note: str


TARGETS = [
    Target(
        name="fed",
        arxiv_url="https://arxiv.org/abs/2006.12719",
        repo_url="https://github.com/Shikib/fed.git",
        repo_dir=Path("/tmp/real-fed"),
        note="Mehri & Eskenazi 2020 'Unsupervised Evaluation of Interactive Dialog with DialoGPT'. Repo has documented issue #3: users cannot reproduce the paper's turn-level FED scores.",
        questions=[
            "Does the evaluation script match the paper's reported numbers exactly, or are there post-processing differences?",
            "Are there any hard-coded model checkpoints or tokenizer versions that could cause the results to drift over time?",
            "Does this repo contain an eval.py or analogous entrypoint? If so, what does it compute?",
        ],
    ),
    Target(
        name="tabm",
        arxiv_url="https://arxiv.org/abs/2410.24210",
        repo_url="https://github.com/yandex-research/tabm.git",
        repo_dir=Path("/tmp/real-tabm"),
        note="Gorishniy et al. 2024/2025 'TabM: Advancing Tabular Deep Learning with Parameter-Efficient Ensembling' (ICLR 2025). Clean baseline — we expect the agent to honestly report 'no obvious leakage' rather than invent a bug.",
        questions=[
            "Is the train/validation/test split leak-free? Any normalization or feature engineering fit on the full dataset before splitting?",
            "Does the repo use group-aware splits when the underlying benchmark has a grouping column, or does it rely on random row-level splits?",
            "Are model checkpoints evaluated on the test set multiple times with different hyperparameters (test-set contamination via selection)?",
        ],
    ),
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


async def _ingest_paper(target: Target, out_dir: Path) -> dict:
    t0 = time.monotonic()
    paper = await ingest(target.arxiv_url)
    dt = time.monotonic() - t0
    (out_dir / "paper_meta.json").write_text(json.dumps({
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
    (out_dir / "paper_full.md").write_text(paper.full_markdown)
    return {
        "title": paper.title,
        "authors": paper.authors[:3],
        "arxiv_id": paper.arxiv_id,
        "markdown_chars": len(paper.full_markdown),
        "sections": len(paper.sections),
        "ingest_duration_s": round(dt, 2),
    }


def _clone_repo(target: Target) -> dict:
    if target.repo_dir.exists():
        shutil.rmtree(target.repo_dir)
    t0 = time.monotonic()
    result = subprocess.run(
        ["git", "clone", "--depth", "1", target.repo_url, str(target.repo_dir)],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr}")
    dt = time.monotonic() - t0
    py_files = list(target.repo_dir.rglob("*.py"))
    ipynb_files = list(target.repo_dir.rglob("*.ipynb"))
    size = sum(f.stat().st_size for f in target.repo_dir.rglob("*") if f.is_file())
    return {
        "url": target.repo_url,
        "local_path": str(target.repo_dir),
        "clone_duration_s": round(dt, 2),
        "py_file_count": len(py_files),
        "ipynb_file_count": len(ipynb_files),
        "clone_size_mb": round(size / 1024 / 1024, 2),
    }


async def _quick_check(repo_dir: Path, question: str) -> QuickCheckResult:
    result = QuickCheckResult(question=question)
    config = RunConfig.from_dict(
        mode="check",
        run_id=f"rb-{int(time.time()*1000)}",
        raw={
            "repo_path": str(repo_dir),
            "question": question,
            "max_budget_usd": 1.0,
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


async def _run_one_target(target: Target) -> tuple[float, int]:
    """Run everything for one target, saving to disk. Returns (cost, n_verdicts)."""
    print(f"\n══ {target.name.upper()} ══")
    print(f"  {target.note}")
    out_dir = OUT_ROOT / target.name
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "questions.txt").write_text("\n\n".join(target.questions))

    print("  ── ingest paper ──")
    paper_info = await _ingest_paper(target, out_dir)
    print(f"    title: {paper_info['title'][:80]}")
    print(f"    {paper_info['markdown_chars']} chars / {paper_info['sections']} sections / {paper_info['ingest_duration_s']}s")

    print("  ── clone repo ──")
    repo_info = _clone_repo(target)
    print(f"    {repo_info['py_file_count']} .py + {repo_info['ipynb_file_count']} .ipynb "
          f"({repo_info['clone_size_mb']} MB in {repo_info['clone_duration_s']}s)")

    total_cost = 0.0
    checks: list[QuickCheckResult] = []
    n_verdicts = 0
    for i, q in enumerate(target.questions, 1):
        print(f"\n  Q{i}: {q[:100]}{'…' if len(q) > 100 else ''}")
        r = await _quick_check(target.repo_dir, q)
        checks.append(r)
        total_cost += r.cost_usd
        if r.verdict is not None and not r.crashed:
            n_verdicts += 1
            print(f"    ✓ {r.verdict!r} conf={r.confidence} ev={len(r.evidence)} "
                  f"turns={r.tool_calls} dur={r.duration_s}s cost=${r.cost_usd:.4f}")
            print(f"      notes: {(r.notes or '')[:180]}")
        elif r.crashed:
            print(f"    ✗ CRASH: {r.error}")
        else:
            print(f"    ✗ no verdict ({r.tool_calls} turns, {r.duration_s}s)")

    summary = {
        "target": target.name,
        "paper": paper_info,
        "repo": repo_info,
        "checks": [asdict(c) for c in checks],
        "n_verdicts": n_verdicts,
        "n_crashes": sum(1 for c in checks if c.crashed),
        "total_cost_usd": round(total_cost, 4),
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC",
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  saved to {out_dir}")
    return total_cost, n_verdicts


async def main() -> int:
    load_env()
    grand_total = 0.0
    grand_verdicts = 0
    grand_questions = 0
    for target in TARGETS:
        cost, n = await _run_one_target(target)
        grand_total += cost
        grand_verdicts += n
        grand_questions += len(target.questions)

    print()
    print("=" * 72)
    print(f"Grand summary: {grand_verdicts}/{grand_questions} verdicts returned, "
          f"total cost ${grand_total:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
