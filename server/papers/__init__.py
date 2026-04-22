"""Paper ingester: arXiv API + docling + on-disk cache."""
from . import cache, ingester
from .ingester import IngestError, ingest
from .models import Paper, Section

__all__ = [
    "IngestError",
    "Paper",
    "Section",
    "cache",
    "ingest",
    "ingester",
]
