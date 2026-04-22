"""Smoke test for the paper ingester.

Runs four probes:
  1. Local `.md` — reads test_data/papers/muchlinski.md directly.
  2. arXiv bare ID — fetches `1603.05629` (ResNet) through the arXiv API +
     docling. First call takes ~15s for docling cold-start.
  3. arXiv abs URL — same paper via different URL shape. Expected: cache hit.
  4. arXiv pdf URL — same paper via .pdf URL. Expected: cache hit.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from server.env import load_env
from server.papers import Paper, ingest

ROOT = Path(__file__).resolve().parent.parent


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


async def main() -> int:
    load_env()

    all_passed = True

    # ── (1) local markdown ─────────────────────────────────────────────
    print("── ingest local markdown ──")
    path = ROOT / "test_data" / "papers" / "muchlinski.md"
    t0 = time.monotonic()
    paper = await ingest(str(path))
    dt = time.monotonic() - t0
    print(f"  took {dt:.2f}s, source_type={paper.source_type!r}, title={paper.title!r}, "
          f"len(full_markdown)={len(paper.full_markdown)}")
    all_passed &= _ok("source_type == 'markdown'", paper.source_type == "markdown")
    all_passed &= _ok("full_markdown is populated", len(paper.full_markdown) > 100)
    all_passed &= _ok("cache_key populated", bool(paper.cache_key))
    print()

    # ── (2) arXiv bare ID (actual ResNet: 1512.03385) ─────────────────
    arxiv_id = "1512.03385"
    print(f"── ingest arXiv bare ID ({arxiv_id} — Deep Residual Learning) ──")
    t0 = time.monotonic()
    paper = await ingest(arxiv_id)
    dt = time.monotonic() - t0
    print(f"  took {dt:.2f}s")
    print(f"  title: {paper.title!r}")
    print(f"  authors[:3]: {paper.authors[:3]}")
    print(f"  arxiv_id: {paper.arxiv_id}")
    print(f"  sections: {len(paper.sections)}")
    print(f"  full_markdown len: {len(paper.full_markdown)}")
    all_passed &= _ok("source_type == 'arxiv'", paper.source_type == "arxiv")
    all_passed &= _ok(
        "title matches ResNet paper",
        "residual" in paper.title.lower() and "deep" in paper.title.lower(),
        paper.title,
    )
    all_passed &= _ok("at least 1 author", len(paper.authors) >= 1)
    all_passed &= _ok("arxiv_id matches", paper.arxiv_id == arxiv_id)
    all_passed &= _ok("abstract is non-empty", len(paper.abstract) > 50)
    all_passed &= _ok("markdown is substantive (>5K chars)", len(paper.full_markdown) > 5_000)
    all_passed &= _ok("section count >= 3", len(paper.sections) >= 3,
                      f"{len(paper.sections)} sections")
    print()

    # ── (3) arXiv abs URL (different URL shape → different cache key) ──
    print(f"── ingest arXiv abs URL https://arxiv.org/abs/{arxiv_id} ──")
    t0 = time.monotonic()
    paper = await ingest(f"https://arxiv.org/abs/{arxiv_id}")
    dt = time.monotonic() - t0
    print(f"  took {dt:.2f}s")
    all_passed &= _ok("arxiv_id still correct", paper.arxiv_id == arxiv_id)
    all_passed &= _ok(
        "title matches ResNet paper",
        "residual" in paper.title.lower() and "deep" in paper.title.lower(),
    )
    print()

    # ── (4) cache hit on the exact same URL ─────────────────────────────
    print(f"── ingest same arXiv abs URL again (expect cache hit) ──")
    t0 = time.monotonic()
    paper = await ingest(f"https://arxiv.org/abs/{arxiv_id}")
    dt = time.monotonic() - t0
    print(f"  took {dt:.2f}s (should be fast)")
    all_passed &= _ok("cache hit returns in < 500ms", dt < 0.5, f"{dt:.3f}s")
    print()

    if all_passed:
        print("PAPER INGESTER SMOKE PASS")
        return 0
    print("PAPER INGESTER SMOKE FAIL")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
