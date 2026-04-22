"""On-disk JSON cache for ingested papers, keyed by sha256(url)[:16]."""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from .models import Paper

log = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = Path(os.environ.get(
    "REPRO_PAPER_CACHE",
    str(Path.home() / ".cache" / "paper-trail" / "papers"),
))


def cache_key_for(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _cache_path(key: str, cache_dir: Path | None = None) -> Path:
    d = cache_dir or _DEFAULT_CACHE_DIR
    return d / f"{key}.json"


def load(url: str, *, cache_dir: Path | None = None) -> Paper | None:
    key = cache_key_for(url)
    path = _cache_path(key, cache_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Paper.from_dict(data)
    except (json.JSONDecodeError, KeyError) as exc:
        log.warning("cache file %s is malformed: %s", path, exc)
        return None


def save(paper: Paper, *, cache_dir: Path | None = None) -> None:
    key = paper.cache_key or cache_key_for(paper.source_url)
    path = _cache_path(key, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(paper.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    log.debug("saved paper to cache: %s", path)
