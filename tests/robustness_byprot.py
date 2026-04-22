"""Robustness test on a totally new domain: protein language models +
evaluation-set data leakage.

Paper: Hermann et al. 2024, "Beware of Data Leakage from Protein LLM
Pretraining" (bioRxiv 10.1101/2024.07.23.604678, July 2024). Shows that
ESM2 pretrained on UniRef50 leaks sequences into downstream evaluation
benchmarks, inflating reported accuracy by ~11%.

Repo: https://github.com/BytedProtein/ByProt — the LM-Design / ProteinMPNN
integration that the paper flags as affected. The repo's GitHub issue #3
raises exactly this concern.

This is a domain shift from our previous tests (tabular ML, dialog eval,
diffusion LMs) and exercises our bioRxiv/PDF ingestion path for the first
time.

All Quick Checks run read-only. Outputs saved to
`test_data/real_papers/byprot/`.
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
OUT_DIR = ROOT / "test_data" / "real_papers" / "byprot"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# bioRxiv PDFs live at the .full.pdf suffix.
PAPER_URL = "https://www.biorxiv.org/content/10.1101/2024.07.23.604678v1.full.pdf"
REPO_URL = "https://github.com/BytedProtein/ByProt.git"
REPO_DIR = Path("/tmp/real-byprot")


QUESTIONS = [
    "Does the evaluation pipeline explicitly filter sequences that were in UniRef50 (the ESM2 pretraining corpus) out of downstream test sets, or does it rely on the upstream data split as-is without such filtering?",
    "Is there a configurable sequence-identity threshold (e.g., MMseqs2 / CD-HIT clustering) applied when constructing train/validation/test splits for CATH-based inverse folding, or does the repo trust the default random split?",
    "Does the repo pin the version or commit of any external pretrained models it loads (ESM2, AlphaFold weights, etc.), or does it fetch from an unpinned source that could silently drift?",
    "For protein design evaluation, does the metric implementation (sequence recovery, perplexity, structural self-consistency) match the cited reference method or is it a custom variant?",
    "Are there any tests or scripts in the repo that detect / warn about train-test sequence overlap, or is this left entirely to the user to audit manually?",
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


async def _ingest_paper() -> dict:
    """Try to ingest the paper. bioRxiv is Cloudflare-blocked, so this
    commonly fails for us. We return a stub in that case — Quick Check
    doesn't need paper context.
    """
    print("── ingesting paper (bioRxiv PDF via docling) ──")
    t0 = time.monotonic()
    try:
        paper = await ingest(PAPER_URL)
    except Exception as exc:
        print(f"  direct ingest failed ({type(exc).__name__}: {exc})")
        # Try curl fallback
        local = Path("/tmp/byprot-paper.pdf")
        try:
            subprocess.run(
                ["curl", "-sSL", "-A", "Mozilla/5.0 paper-trail/0.1",
                 "-o", str(local), PAPER_URL],
                check=True, timeout=60, capture_output=True,
            )
            # Check if what we got is actually a PDF (curl might have been
            # served an HTML Cloudflare challenge page).
            head = local.read_bytes()[:8]
            if not head.startswith(b"%PDF"):
                raise RuntimeError(
                    "bioRxiv returned a Cloudflare challenge page instead of the PDF"
                )
            paper = await ingest(str(local))
        except Exception as exc2:
            # This is a KNOWN LIMITATION: our fetch pipeline doesn't defeat
            # Cloudflare bot protection. We'll document it here so the
            # user can see it in run_summary.json.
            dt = time.monotonic() - t0
            print(
                f"  curl fallback also failed: {exc2}\n"
                "  ⚠ recording 'unavailable' and proceeding with repo-only checks."
            )
            status = {
                "source_url": PAPER_URL,
                "ingest_status": "unavailable",
                "reason": "bioRxiv is behind Cloudflare bot protection; "
                          "both httpx and curl User-Agent spoofing were blocked. "
                          "Workaround: download the PDF manually in a browser and "
                          "pass a local file path to ingest().",
                "ingest_duration_s": round(dt, 2),
            }
            (OUT_DIR / "paper_meta.json").write_text(json.dumps(status, indent=2))
            return status

    dt = time.monotonic() - t0
    print(f"  title: {paper.title!r}")
    print(f"  sections: {len(paper.sections)}, markdown chars: {len(paper.full_markdown)}")
    print(f"  duration: {dt:.2f}s")

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
        "ingest_status": "ok",
    }, indent=2))
    (OUT_DIR / "paper_full.md").write_text(paper.full_markdown)

    return {
        "title": paper.title,
        "authors": paper.authors[:3],
        "markdown_chars": len(paper.full_markdown),
        "sections": len(paper.sections),
        "ingest_duration_s": round(dt, 2),
        "ingest_status": "ok",
    }


def _clone_repo() -> dict:
    print()
    print(f"── cloning {REPO_URL} ──")
    if REPO_DIR.exists():
        shutil.rmtree(REPO_DIR)
    t0 = time.monotonic()
    subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(REPO_DIR)],
        capture_output=True, text=True, timeout=120, check=True,
    )
    dt = time.monotonic() - t0
    py_files = list(REPO_DIR.rglob("*.py"))
    ipynb_files = list(REPO_DIR.rglob("*.ipynb"))
    size = sum(f.stat().st_size for f in REPO_DIR.rglob("*") if f.is_file())
    print(f"  clone duration: {dt:.2f}s")
    print(f"  .py: {len(py_files)}, .ipynb: {len(ipynb_files)}, size: {size/1024/1024:.1f} MB")
    return {
        "url": REPO_URL,
        "local_path": str(REPO_DIR),
        "clone_duration_s": round(dt, 2),
        "py_file_count": len(py_files),
        "ipynb_file_count": len(ipynb_files),
        "clone_size_mb": round(size / 1024 / 1024, 2),
    }


async def _quick_check(question: str) -> QuickCheckResult:
    r = QuickCheckResult(question=question)
    cfg = RunConfig.from_dict(
        mode="check",
        run_id=f"byprot-{int(time.time()*1000)}",
        raw={
            "repo_path": str(REPO_DIR),
            "question": question,
            "max_budget_usd": 1.5,
        },
    )
    t0 = time.monotonic()
    async for ev in run_agent(cfg):
        if ev["type"] == "tool_call":
            r.tool_calls += 1
        elif ev["type"] == "quick_check_verdict":
            d = ev["data"]
            r.verdict = d.get("verdict")
            r.confidence = d.get("confidence")
            r.evidence = d.get("evidence") or []
            r.notes = d.get("notes")
        elif ev["type"] == "error":
            r.crashed = True
            r.error = ev["data"].get("message", "unknown")
        elif ev["type"] == "session_end":
            r.cost_usd = float(ev["data"].get("cost_usd", 0.0))
            break
    r.duration_s = round(time.monotonic() - t0, 2)
    return r


async def main() -> int:
    load_env()

    # Paper ingest is best-effort — bioRxiv Cloudflare blocking is a known
    # limitation we document rather than letting it fail the whole probe.
    paper_info = await _ingest_paper()

    try:
        repo_info = _clone_repo()
    except Exception as exc:
        print(f"FAIL: repo clone: {exc}")
        return 1

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

    summary = {
        "paper": paper_info,
        "repo": repo_info,
        "checks": [asdict(c) for c in checks],
        "n_verdicts": sum(1 for c in checks if c.verdict),
        "n_crashes": sum(1 for c in checks if c.crashed),
        "total_cost_usd": round(total_cost, 4),
        "run_date": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()) + " UTC",
    }
    (OUT_DIR / "run_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (OUT_DIR / "questions.txt").write_text("\n\n".join(QUESTIONS))
    print()
    print(f"── saved to {OUT_DIR} ──")
    for f in sorted(OUT_DIR.iterdir()):
        size = f.stat().st_size
        print(f"  {f.name}  ({size:,} bytes)")
    print()
    print(f"total cost: ${total_cost:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
