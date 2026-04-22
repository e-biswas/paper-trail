"""docling-based PDF → markdown wrapper.

docling's first call loads multiple ML models (~15s cold-start on a
laptop); subsequent calls are fast. We singleton the `DocumentConverter`
at module scope. All conversion runs on a thread so the event loop isn't
blocked.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

_CONVERTER = None
_CONVERTER_LOCK = asyncio.Lock()


async def _get_converter():
    """Lazy-init the DocumentConverter. Safe under concurrent awaits."""
    global _CONVERTER
    if _CONVERTER is not None:
        return _CONVERTER
    async with _CONVERTER_LOCK:
        if _CONVERTER is None:
            log.info("docling: loading models (first call; ~15s expected)")
            from docling.document_converter import DocumentConverter
            _CONVERTER = await asyncio.to_thread(DocumentConverter)
            log.info("docling: ready")
    return _CONVERTER


async def parse_pdf(source: str | Path) -> tuple[str, dict]:
    """Convert a PDF (URL or local path) to markdown + metadata.

    Returns (markdown, metadata_dict). `metadata_dict` includes `title` if
    docling could extract one, plus `page_count` if available.
    """
    src = str(source)
    converter = await _get_converter()
    # DocumentConverter.convert is blocking; run on a thread.
    result = await asyncio.to_thread(converter.convert, src)
    document = result.document
    md = document.export_to_markdown()

    title = ""
    m = re.match(r"^\s*#\s+(.+?)\s*$", md, re.MULTILINE)
    if m:
        title = m.group(1).strip()

    return md, {
        "title": title,
        "page_count": getattr(document, "num_pages", lambda: None)() if hasattr(document, "num_pages") else None,
    }
