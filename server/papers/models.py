"""Domain model for papers after ingestion."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Section:
    title: str
    level: int
    markdown: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Paper:
    """Normalized view of an ingested paper."""

    source_url: str
    source_type: str             # "arxiv" | "pdf" | "markdown"
    title: str
    abstract: str
    authors: list[str]
    arxiv_id: str | None
    sections: list[Section]
    full_markdown: str
    ingested_at: str             # ISO timestamp
    cache_key: str               # sha256(url)[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["sections"] = [s.to_dict() if isinstance(s, Section) else s for s in self.sections]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Paper":
        sections = [
            Section(title=s.get("title", ""), level=int(s.get("level", 1)),
                    markdown=s.get("markdown", ""))
            for s in (d.get("sections") or [])
        ]
        return cls(
            source_url=d["source_url"],
            source_type=d["source_type"],
            title=d.get("title", ""),
            abstract=d.get("abstract", ""),
            authors=list(d.get("authors") or []),
            arxiv_id=d.get("arxiv_id"),
            sections=sections,
            full_markdown=d.get("full_markdown", ""),
            ingested_at=d.get("ingested_at", ""),
            cache_key=d.get("cache_key", ""),
        )
