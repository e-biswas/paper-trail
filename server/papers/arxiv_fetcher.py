"""arXiv paper fetcher.

Uses the `arxiv` package for metadata. For the paper body we download the
PDF (via arxiv's built-in downloader) and run it through docling — this is
robust across old papers where the raw LaTeX tarball is missing, and still
cheaper than re-implementing a LaTeX→markdown converter.

arXiv IDs accepted in any of:
  - bare: "1603.05629"
  - abs URL: "https://arxiv.org/abs/1603.05629"
  - pdf URL: "https://arxiv.org/pdf/1603.05629" (with or without ".pdf")
"""
from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import arxiv

from .models import Paper, Section
from .pdf_parser import parse_pdf

log = logging.getLogger(__name__)


_ARXIV_ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf)/)?([a-z\-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$",
    re.IGNORECASE,
)


class ArxivFetchError(RuntimeError):
    """Raised when we can't fetch an arXiv paper."""


def _extract_arxiv_id(source: str) -> str | None:
    """Pull the arXiv ID from any accepted form, or None if not arXiv-shaped."""
    m = _ARXIV_ID_RE.search(source.strip())
    return m.group(1) if m else None


async def fetch(source_url: str) -> Paper:
    arxiv_id = _extract_arxiv_id(source_url)
    if not arxiv_id:
        raise ArxivFetchError(f"could not extract arXiv ID from {source_url!r}")

    log.info("arxiv: fetching metadata for %s", arxiv_id)

    def _blocking_fetch():
        search = arxiv.Search(id_list=[arxiv_id])
        client = arxiv.Client()
        return next(iter(client.results(search)))

    result = await asyncio.to_thread(_blocking_fetch)
    title = result.title.strip()
    abstract = (result.summary or "").strip()
    authors = [a.name for a in result.authors]

    # Download the PDF into a temp dir.
    with tempfile.TemporaryDirectory(prefix="arxiv-") as tmp:
        pdf_filename = f"{arxiv_id.replace('/', '_')}.pdf"
        log.info("arxiv: downloading PDF for %s", arxiv_id)
        pdf_path: str = await asyncio.to_thread(
            result.download_pdf, dirpath=tmp, filename=pdf_filename
        )
        log.info("arxiv: parsing PDF via docling…")
        body_md, _meta = await parse_pdf(pdf_path)

    sections = _split_into_sections(body_md)

    # Compose the final markdown with metadata header.
    full_md = (
        f"# {title}\n\n"
        f"**arXiv:** {arxiv_id}  \n"
        f"**Authors:** {', '.join(authors) if authors else '(unknown)'}\n\n"
        f"## Abstract\n\n{abstract}\n\n"
        f"## Body\n\n{body_md}\n"
    )

    from .cache import cache_key_for

    return Paper(
        source_url=source_url,
        source_type="arxiv",
        title=title,
        abstract=abstract,
        authors=authors,
        arxiv_id=arxiv_id,
        sections=sections,
        full_markdown=full_md,
        ingested_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        cache_key=cache_key_for(source_url),
    )


def _split_into_sections(markdown: str) -> list[Section]:
    """Split a markdown body on heading lines. Preserves heading level."""
    sections: list[Section] = []
    current_title = "Preamble"
    current_level = 1
    current_lines: list[str] = []

    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    for line in markdown.splitlines():
        m = heading_re.match(line)
        if m:
            if current_lines:
                sections.append(Section(
                    title=current_title,
                    level=current_level,
                    markdown="\n".join(current_lines).strip(),
                ))
            current_level = len(m.group(1))
            current_title = m.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append(Section(
            title=current_title,
            level=current_level,
            markdown="\n".join(current_lines).strip(),
        ))

    return [s for s in sections if s.markdown]
