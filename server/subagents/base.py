"""Shared types + helpers for subagents.

Each subagent module exports one async function that takes the conductor's
request, runs an inner `claude_agent_sdk.query()` with a narrow prompt and
tool allowlist, parses the structured result block from the output, and
returns a `SubagentResult`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class SubagentResult:
    """Narrow, strongly-typed output every subagent returns."""

    ok: bool
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    cost_usd: float = 0.0
    duration_ms: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------- #
# Parsing the structured result block
# ---------------------------------------------------------------------- #


_RESULT_HEADER_RE = re.compile(
    r"^## (AuditResult|RunResult|PaperSummary|ValidityReport|Verdict)\s*:\s*$",
    re.MULTILINE,
)


def extract_result_block(text: str, *, expected_kind: str) -> dict[str, Any] | None:
    """Locate the first `## <expected_kind>:` block in `text` and parse its
    body into a dict. Returns None if the block is absent or malformed.
    """
    for m in _RESULT_HEADER_RE.finditer(text):
        if m.group(1) != expected_kind:
            continue
        body_start = m.end()
        next_header = _RESULT_HEADER_RE.search(text, body_start)
        body = text[body_start : next_header.start() if next_header else len(text)]
        parsed = _parse_yaml_ish(body)
        if parsed:
            return parsed
    return None


def _parse_yaml_ish(body: str) -> dict[str, Any]:
    """Same deliberately-narrow YAML-ish parser we use in `server.parser`,
    duplicated here (not imported) so the subagent module is standalone.
    """
    from server.parser import _parse_body  # reuse the tested implementation

    return _parse_body(body.strip("\n"))


def cost_from_result_message(msg: Any) -> float:
    """Pull total_cost_usd from a ResultMessage, defensively."""
    try:
        return float(getattr(msg, "total_cost_usd", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def duration_from_result_message(msg: Any) -> int:
    try:
        return int(getattr(msg, "duration_ms", 0) or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------- #
# Prompt loading
# ---------------------------------------------------------------------- #


_PROMPT_DIR = None


def load_subagent_prompt(name: str) -> str:
    """Load a subagent prompt by name (e.g. 'code_auditor')."""
    from pathlib import Path

    global _PROMPT_DIR
    if _PROMPT_DIR is None:
        _PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts" / "subagents"
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"subagent prompt not found: {path}")
    return path.read_text(encoding="utf-8")
