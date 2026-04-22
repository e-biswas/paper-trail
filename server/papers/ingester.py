"""Dispatch between the arXiv and docling backends, with on-disk caching.

Public entry point: `ingest(url_or_path, *, force_refresh=False) -> Paper`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from . import cache
from .arxiv_fetcher import ArxivFetchError, _extract_arxiv_id, fetch as fetch_arxiv
from .models import Paper
from .pdf_parser import parse_pdf

log = logging.getLogger(__name__)


class IngestError(RuntimeError):
    """Raised for any terminal failure during paper ingestion."""


async def ingest(url_or_path: str, *, force_refresh: bool = False) -> Paper:
    """Turn an arbitrary paper reference into a `Paper`.

    Dispatch rules (in order of preference):
      1. arXiv-shaped inputs (abs URL / pdf URL / bare id) → arXiv API + docling.
      2. Local `.md` / `.markdown` / `.tex` file path → read directly as markdown.
      3. Local `.pdf` path → docling.
      4. Any other URL ending `.pdf` → docling after download.
      5. Otherwise → `IngestError`.
    """
    source = url_or_path.strip()
    if not source:
        raise IngestError("empty paper URL / path")

    cached = cache.load(source) if not force_refresh else None
    if cached:
        log.info("paper cache hit: %s", source)
        return cached

    paper: Paper | None = None

    # (1) arXiv
    arxiv_id = _extract_arxiv_id(source)
    if arxiv_id:
        try:
            paper = await fetch_arxiv(source)
        except ArxivFetchError as exc:
            raise IngestError(f"arXiv fetch failed: {exc}") from exc

    # (2) local markdown / tex
    elif source.startswith("file://") or Path(source).exists():
        path = Path(source[len("file://"):]) if source.startswith("file://") else Path(source)
        if path.suffix.lower() in {".md", ".markdown", ".tex"}:
            md = path.read_text(encoding="utf-8")
            title_line = next((ln for ln in md.splitlines() if ln.strip().startswith("#")), "")
            title = title_line.lstrip("#").strip() or path.stem
            paper = Paper(
                source_url=source,
                source_type="markdown",
                title=title,
                abstract="",
                authors=[],
                arxiv_id=None,
                sections=[],
                full_markdown=md,
                ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                cache_key=cache.cache_key_for(source),
            )
        elif path.suffix.lower() == ".pdf":
            md, meta = await parse_pdf(str(path))
            paper = Paper(
                source_url=source,
                source_type="pdf",
                title=meta.get("title") or path.stem,
                abstract="",
                authors=[],
                arxiv_id=None,
                sections=[],
                full_markdown=md,
                ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                cache_key=cache.cache_key_for(source),
            )

    # (3) remote PDF
    elif source.lower().endswith(".pdf") and (source.startswith("http://") or source.startswith("https://")):
        md, meta = await parse_pdf(source)
        paper = Paper(
            source_url=source,
            source_type="pdf",
            title=meta.get("title", ""),
            abstract="",
            authors=[],
            arxiv_id=None,
            sections=[],
            full_markdown=md,
            ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            cache_key=cache.cache_key_for(source),
        )

    if paper is None:
        raise IngestError(f"unsupported paper source: {source!r}")

    cache.save(paper)
    return paper
