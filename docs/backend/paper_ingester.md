# Backend — Paper Ingester

## Purpose

Turn an arbitrary paper URL into a structured `Paper` object the conductor and subagents can read. Two backends behind one interface: **arXiv API** for arXiv URLs (raw LaTeX is cleaner than any PDF parser), **docling** for everything else. Results are cached on disk by URL hash so repeat runs skip re-parsing.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```python
# server/papers/models.py
@dataclass
class Paper:
    source_url: str
    source_type: Literal["arxiv", "pdf"]
    title: str
    abstract: str
    authors: list[str]
    arxiv_id: str | None         # e.g. "1603.05629"
    sections: list[Section]      # markdown body split on headings
    full_markdown: str           # reassembled for agent ingestion
    ingested_at: str             # ISO timestamp
    cache_key: str               # sha256(source_url)[:16]

@dataclass
class Section:
    title: str
    level: int                   # 1, 2, 3 heading level
    markdown: str
```

```python
# server/papers/ingester.py
async def ingest(url_or_path: str, *, force_refresh: bool = False) -> Paper:
    """
    Dispatches to the right backend based on URL shape.
    Caches by sha256(source_url)[:16] at ~/.cache/paper-trail/papers/.
    """
```

## Dispatch rules

| Input | Backend |
|---|---|
| `https://arxiv.org/abs/<id>`, `https://arxiv.org/pdf/<id>`, or a bare `<id>` | `arxiv_fetcher.fetch(id)` |
| Any other URL ending `.pdf` or returning `application/pdf` | `pdf_parser.parse(url)` via `docling` |
| Local file path ending `.pdf` | `pdf_parser.parse(local_path)` via `docling` |
| Local file path ending `.md` or `.tex` | Read directly, no parsing (for test fixtures) |
| Anything else | `ingest()` raises `UnsupportedPaperSource` |

## Implementation notes

### arXiv backend

Uses the official [`arxiv`](https://pypi.org/project/arxiv/) Python package (wraps the public arXiv API) for metadata, and downloads the **raw LaTeX source tarball** (`e-print` endpoint) for the body. Raw LaTeX is vastly cleaner than PDF text extraction: we get the actual section structure, math, and bibliography.

Flow:

```python
# server/papers/arxiv_fetcher.py
import arxiv, tarfile, tempfile, httpx, re

async def fetch(arxiv_id: str) -> Paper:
    search = arxiv.Search(id_list=[arxiv_id])
    result = next(arxiv.Client().results(search))
    # metadata: title, abstract, authors, ...
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://arxiv.org/e-print/{arxiv_id}")
        resp.raise_for_status()
    # Extract, find main .tex, concat included files, strip comments,
    # convert to markdown with a light pandoc subprocess OR a manual
    # tex→markdown pass (keep it narrow: sections, paragraphs, math inline).
    full_md = _tex_to_markdown(tar_payload)
    return Paper(source_type="arxiv", arxiv_id=arxiv_id, ..., full_markdown=full_md)
```

**LaTeX → markdown** path: a minimal converter is enough. We don't need perfect fidelity; we need the paper readable enough for the agent to extract claims. Candidates:
- `pandoc` (subprocess) — best quality, ~100 MB external dependency. If available on the box, use it. Otherwise fall back.
- Hand-rolled converter — keep sections (`\section` → `##`), paragraphs, emphasis, inline math `$...$` preserved as-is. Drop bibliographies, figures, tables.

MVP: try `pandoc` via subprocess first (wrapped in try/except); fall back to a small hand-rolled pass if not installed. Cache the output.

### PDF backend (docling)

Uses [`docling`](https://github.com/docling-project/docling) (IBM Research, Apache 2.0). docling preserves structure (headings, paragraphs, code, tables) and outputs Markdown natively.

```python
# server/papers/pdf_parser.py
from docling.document_converter import DocumentConverter

_CONVERTER: DocumentConverter | None = None

def _converter() -> DocumentConverter:
    global _CONVERTER
    if _CONVERTER is None:
        _CONVERTER = DocumentConverter()
    return _CONVERTER

async def parse(source: str | Path) -> Paper:
    # Blocking library; run in a thread to avoid stalling the event loop.
    result = await asyncio.to_thread(_converter().convert, str(source))
    md = result.document.export_to_markdown()
    # Extract title/abstract via regex on the top of the rendered markdown.
    return _build_paper_from_markdown(md, source)
```

Notes:
- docling's first call is slow (~5–15s cold start because of model loading). Subsequent calls fast. Singleton the `DocumentConverter` at module level.
- Run in an executor thread so FastAPI's event loop isn't blocked.
- Pin a known-good docling version in `pyproject.toml`.

### Cache

```
~/.cache/paper-trail/papers/
  <cache_key>.json     # serialized Paper
  <cache_key>.raw      # raw source (tex tarball or PDF bytes) — optional
```

`ingest()` checks cache first; `force_refresh=True` bypasses.

### Section extraction

After we have `full_markdown`, `_split_into_sections(md)` walks the headings and produces a list of `Section` objects. Clean, predictable, makes it easy for the agent to request "section 3" by name.

### Claim extraction

**Not in this module.** The Paper Reader subagent reads the `full_markdown` and emits claims. Paper Ingester is deliberately dumb — just get bytes → markdown.

### Error handling

- Network failures: retry 2× with exponential backoff; after that, raise `IngestError` with a clear message (WS surfaces it as an `error` envelope).
- docling crashes on malformed PDFs: catch, raise `IngestError("docling_parse_failed: <detail>")`.
- LaTeX tarball missing from arXiv: fall back to downloading the PDF and running docling on it.
- Paper > 10 MB: warn + proceed, but truncate full_markdown to 100k chars before returning to protect the agent's context.

### Security

All inputs are URLs — no user code execution here. But:
- Validate URLs against an allowlist of schemes (`https`, `http`, `file://` for local test paths).
- Hard-cap download size (50 MB) to prevent memory blowup.
- docling runs in-process; it's a known library, not user code, so no extra sandboxing.
- Never follow redirects to `localhost`, `127.0.0.1`, `169.254.*`, or RFC-1918 addresses (SSRF prevention) when fetching arbitrary PDF URLs.

## How to verify (end-to-end)

### Setup

`uv sync` brings in `arxiv`, `httpx`, `docling`. `pandoc` installed via system package manager is optional.

### Smoke tests

1. **arXiv happy path:** `await ingest("https://arxiv.org/abs/1603.05629")` (Deep Residual Learning) → Paper with `source_type="arxiv"`, `title` matches "Deep Residual Learning for Image Recognition", `arxiv_id="1603.05629"`, `len(sections) >= 3`, first section is "Introduction" (or similar).

2. **arXiv PDF URL variant:** `await ingest("https://arxiv.org/pdf/1603.05629.pdf")` → same result as abstract URL (the fetcher strips `pdf` and the `.pdf` suffix before hitting the API).

3. **arXiv bare ID:** `await ingest("1603.05629")` → same result.

4. **Arbitrary PDF:** ingest a small research PDF (a paper checked into `test_data/papers/` as an actual PDF) → Paper with `source_type="pdf"`, readable `full_markdown`, sections present.

5. **Cache hit:** second call for the same URL returns in < 100 ms (no network, no docling run).

6. **Error:** `await ingest("https://example.com/not-a-paper")` → raises `IngestError`.

### Expected failure modes and how to diagnose

- **docling downloads models on first run.** Slow. Warm the cache before the live demo by ingesting the demo papers once during setup.
- **Pandoc missing → hand-rolled converter output is ugly.** Check by diffing the markdown against a known-good version.
- **arXiv rate limits.** 1 req/sec per client. Our flow is nowhere near this.

## Open questions / deferred

- Math preservation quality in docling output is variable. If the agent needs high-fidelity equations, we may need a post-processing pass using mathpix or similar. `DEFERRED` — MVP's agent reasons about code, not equations.
- Citation graph extraction. `DEFERRED`.
- Non-English papers. Out of scope for MVP.
- Paper Reader auto-caches claim summaries. Can be layered on top; not in MVP.
