"""Markdown-section parser for Paper Trail agent output.

The agent is instructed to emit structured markdown with a fixed set of
section headers. This parser walks the text, detects completed sections, and
emits envelope-shaped dicts ready to wrap in the WS transport.

The parser is defensive by design:
- Unknown section names are ignored (no event emitted).
- Sections with malformed bodies emit nothing and a warning is logged.
- The caller can recover from any badly-formed agent output without crashing.

See `docs/integration.md` for the event schema and
`docs/backend/agent.md#stateful-markdown-section-parser` for the header
vocabulary. Golden tests live in `test_data/parser/expected/`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section header regexes
# ---------------------------------------------------------------------------

# Match ONE header line. We split on these anchors.
_HEADER_LINE = re.compile(r"^## (.+?)\s*$", re.MULTILINE)

_HYPOTHESIS_RE = re.compile(r"^Hypothesis\s+(\d+):\s*(.+?)$")
_HYPOTHESIS_UPDATE_RE = re.compile(r"^Hypothesis\s+(\d+)\s*\(update\)\s*:\s*$")
_DOSSIER_RE = re.compile(r"^Dossier\s*[—–-]\s*(.+?)\s*:\s*$")
_SIMPLE_RE = re.compile(r"^([A-Za-z][A-Za-z ]*?)\s*:\s*$")


DOSSIER_SECTION_MAP: dict[str, str] = {
    "claim tested": "claim_tested",
    "evidence gathered": "evidence_gathered",
    "root cause": "root_cause",
    "fix applied": "fix_applied",
    "remaining uncertainty": "remaining_uncertainty",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse(text: str) -> list[dict[str, Any]]:
    """Parse a complete agent output into a list of envelope dicts.

    Returns dicts shaped `{"type": str, "data": {...}}`. Run-level envelope
    fields (`run_id`, `ts`, `seq`) are added by the caller.
    """
    events: list[dict[str, Any]] = []
    # Track hypothesis rank → id assignment so `hypothesis_update` events can
    # carry the same id as the original `hypothesis` event.
    hypothesis_ids: dict[int, str] = {}
    check_counter = 0
    finding_counter = 0

    for header, body in _iter_sections(text):
        try:
            event = _dispatch(
                header, body,
                hypothesis_ids=hypothesis_ids,
                check_counter=check_counter,
                finding_counter=finding_counter,
            )
        except Exception as exc:  # defensive — never raise to the caller
            log.warning("parser failed on section %r: %s", header, exc)
            continue

        if event is None:
            continue

        if event["type"] == "check":
            check_counter += 1
        elif event["type"] == "finding":
            finding_counter += 1

        events.append(event)

    return events


# ---------------------------------------------------------------------------
# Section splitting
# ---------------------------------------------------------------------------


def _iter_sections(text: str):
    """Yield (header, body) pairs. `header` is the line after `## `; `body`
    is everything up to (but not including) the next header line or EOF.
    """
    matches = list(_HEADER_LINE.finditer(text))
    if not matches:
        return
    for i, m in enumerate(matches):
        header = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip("\n")
        yield header, body


# ---------------------------------------------------------------------------
# Dispatch — one section → at most one event
# ---------------------------------------------------------------------------


def _dispatch(
    header: str,
    body: str,
    *,
    hypothesis_ids: dict[int, str],
    check_counter: int,
    finding_counter: int,
) -> dict[str, Any] | None:
    """Turn one section into an envelope event dict. Returns None to skip."""
    parsed = _parse_body(body)

    # --- Claim summary ---
    if header.rstrip(":").strip().lower() == "claim":
        claim = parsed.get("claim")
        if not claim:
            return None
        return {"type": "claim_summary", "data": {"claim": claim}}

    # --- Hypothesis (new) ---
    m = _HYPOTHESIS_RE.match(header)
    if m:
        rank = int(m.group(1))
        name = m.group(2).strip()
        try:
            confidence = float(parsed["confidence"])
            reason = parsed["reason"]
        except (KeyError, TypeError, ValueError):
            log.warning("hypothesis header %r missing confidence or reason", header)
            return None
        hid = f"h{rank}"
        hypothesis_ids[rank] = hid
        return {
            "type": "hypothesis",
            "data": {
                "id": hid,
                "rank": rank,
                "name": name,
                "confidence": confidence,
                "reason": reason,
            },
        }

    # --- Hypothesis update ---
    m = _HYPOTHESIS_UPDATE_RE.match(header)
    if m:
        rank = int(m.group(1))
        hid = hypothesis_ids.get(rank, f"h{rank}")
        try:
            confidence = float(parsed["confidence"])
        except (KeyError, TypeError, ValueError):
            log.warning("hypothesis update header %r missing confidence", header)
            return None
        return {
            "type": "hypothesis_update",
            "data": {
                "id": hid,
                "confidence": confidence,
                "reason_delta": parsed.get("reason_delta", ""),
            },
        }

    # --- Check ---
    if header.startswith("Check:"):
        hypothesis_id = parsed.get("hypothesis_id")
        description = parsed.get("description")
        method = parsed.get("method", "")
        if not hypothesis_id or not description:
            log.warning("check section missing hypothesis_id or description")
            return None
        cid = f"c{check_counter + 1}"
        return {
            "type": "check",
            "data": {
                "id": cid,
                "hypothesis_id": hypothesis_id,
                "description": description,
                "method": method,
            },
        }

    # --- Finding ---
    if header.rstrip(":").strip().lower() == "finding":
        check_id = parsed.get("check_id")
        result = parsed.get("result")
        if not check_id or not result:
            log.warning("finding section missing check_id or result")
            return None
        return {
            "type": "finding",
            "data": {
                "id": f"f{finding_counter + 1}",
                "check_id": check_id,
                "result": result,
                "supports": _as_list(parsed.get("supports", [])),
                "refutes": _as_list(parsed.get("refutes", [])),
            },
        }

    # --- Verdict ---
    if header.rstrip(":").strip().lower() == "verdict":
        # Shape differs between Deep Investigation and Quick Check. Quick Check
        # verdicts carry `verdict: confirmed|refuted|unclear`. Deep carries
        # `hypothesis_id` + `summary`.
        if "verdict" in parsed:  # Quick Check
            return {
                "type": "quick_check_verdict",
                "data": {
                    "verdict": parsed["verdict"],
                    "confidence": float(parsed.get("confidence", 0.0)),
                    "evidence": _as_list(parsed.get("evidence", [])),
                    "notes": parsed.get("notes", ""),
                },
            }
        # Deep Investigation verdict
        if "hypothesis_id" in parsed and "summary" in parsed:
            return {
                "type": "verdict",
                "data": {
                    "hypothesis_id": parsed["hypothesis_id"],
                    "confidence": float(parsed.get("confidence", 0.0)),
                    "summary": parsed["summary"],
                },
            }
        log.warning("verdict section missing required fields")
        return None

    # --- Fix applied ---
    if header.rstrip(":").strip().lower() == "fix applied":
        files = _as_list(parsed.get("files_changed", []))
        summary = parsed.get("diff_summary", "")
        if not files:
            return None
        return {
            "type": "fix_applied",
            "data": {"files_changed": files, "diff_summary": summary},
        }

    # --- Metric delta ---
    if header.rstrip(":").strip().lower() == "metric delta":
        try:
            metric = parsed["metric"]
            before = float(parsed["before"])
            after = float(parsed["after"])
        except (KeyError, TypeError, ValueError):
            log.warning("metric delta section missing metric/before/after")
            return None
        data: dict[str, Any] = {
            "metric": metric,
            "before": before,
            "after": after,
            "context": parsed.get("context", ""),
        }
        if "baseline" in parsed:
            try:
                data["baseline"] = float(parsed["baseline"])
            except (TypeError, ValueError):
                pass
        return {"type": "metric_delta", "data": data}

    # --- Dossier section ---
    m = _DOSSIER_RE.match(header)
    if m:
        key = m.group(1).strip().lower()
        section = DOSSIER_SECTION_MAP.get(key)
        if not section:
            log.warning("unknown dossier section %r", key)
            return None
        return {
            "type": "dossier_section",
            "data": {
                "section": section,
                "markdown": body.strip(),
            },
        }

    # --- PR opened ---
    if header.rstrip(":").strip().lower() == "pr opened":
        url = parsed.get("url")
        if not url:
            return None
        number = parsed.get("number")
        try:
            number_int = int(number) if number is not None else None
        except (TypeError, ValueError):
            number_int = None
        return {
            "type": "pr_opened",
            "data": {
                "url": url,
                "number": number_int,
                "title": parsed.get("title", ""),
            },
        }

    # --- Aborted ---
    if header.rstrip(":").strip().lower() == "aborted":
        return {
            "type": "aborted",
            "data": {
                "reason": parsed.get("reason", "unknown"),
                "detail": parsed.get("detail", ""),
            },
        }

    # Unknown header — don't emit anything.
    log.debug("unknown section header %r", header)
    return None


# ---------------------------------------------------------------------------
# Body parser — a tiny YAML-ish subset
# ---------------------------------------------------------------------------


def _parse_body(body: str) -> dict[str, Any]:
    """Parse a section body into a dict.

    Supported shapes:
        key: value
        key: "quoted value"
        key: 3.14
        key: [a, b, c]
        key:
          - nested_key: nested_value
            another_key: another_value
          - nested_key: ...
        key:
          sub_key: sub_value

    Not supported: block scalars (`|`, `>`), anchors, tags, explicit types.
    """
    result: dict[str, Any] = {}
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue

        # Only consider top-level (non-indented) lines here; nested
        # content is consumed by the child parser below.
        if line.startswith((" ", "\t")):
            i += 1
            continue

        if ":" not in line:
            i += 1
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        if value == "":
            # Parent of a nested structure — peek ahead.
            nested_lines = []
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].startswith((" ", "\t"))):
                if lines[j].strip():
                    nested_lines.append(lines[j])
                j += 1
            result[key] = _parse_nested(nested_lines)
            i = j
            continue

        result[key] = _coerce_scalar(value)
        i += 1
    return result


def _parse_nested(lines: list[str]) -> Any:
    """Parse a block of indented lines as either a list of dicts, a flat list,
    or a sub-dict.
    """
    if not lines:
        return None

    # Strip the common leading indent.
    stripped = [_strip_common_indent(lines)]
    normalized = stripped[0]

    # Is it a list? Any line starts with `- `?
    if any(line.lstrip().startswith("- ") for line in normalized):
        return _parse_list_of_records(normalized)

    # Otherwise, treat as a sub-dict.
    sub_body = "\n".join(normalized)
    return _parse_body(sub_body)


def _strip_common_indent(lines: list[str]) -> list[str]:
    """Remove the longest common leading whitespace from all non-empty lines."""
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return lines
    indents = [len(line) - len(line.lstrip()) for line in non_empty]
    common = min(indents)
    return [line[common:] if line[:common].isspace() else line for line in lines]


def _parse_list_of_records(lines: list[str]) -> list[Any]:
    """Parse a YAML-ish list.

    Supports three shapes, chosen per item:

        # (a) scalar strings
        - "split is stratified 75/25"
        - class_weight=balanced

        # (b) records
        - file: foo.py
          line: 47
          snippet: "blah"

        # (c) single key-no-value (degenerate) — treated as scalar
        - h1
    """
    items: list[Any] = []
    buf: list[str] = []

    def _flush() -> None:
        if not buf:
            return
        first = buf[0].lstrip()
        if first.startswith("- "):
            first = first[2:]
        else:
            first = first.lstrip("-").strip()
        rest = buf[1:]

        # Case (a): first line has no colon AND there are no continuation
        # lines → treat it as a scalar string list entry.
        if ":" not in first and not rest:
            items.append(_coerce_scalar(first.strip()))
            buf.clear()
            return

        # Case (b) / (c): parse as a mini-body.
        body_lines = [first] + [line.lstrip() for line in rest]
        item = _parse_body("\n".join(body_lines))

        # Degenerate: empty dict (no keys matched) — fall back to scalar.
        if not item:
            items.append(_coerce_scalar(first.strip()))
            buf.clear()
            return

        # Degenerate: one key with empty-ish value (e.g. `h1:` with nothing after) — scalar.
        if len(item) == 1:
            only_key, only_val = next(iter(item.items()))
            if only_val in (None, "", {}, []):
                items.append(_coerce_scalar(only_key))
                buf.clear()
                return

        items.append(item)
        buf.clear()

    for line in lines:
        if line.lstrip().startswith("- "):
            _flush()
            buf.append(line)
        else:
            buf.append(line)
    _flush()
    return items


# ---------------------------------------------------------------------------
# Scalar coercion
# ---------------------------------------------------------------------------


def _coerce_scalar(value: str) -> Any:
    """Turn a YAML-ish scalar string into a Python primitive."""
    if value == "":
        return ""
    # Quoted string — keep the interior.
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none", "~"):
        return None
    # Try int
    try:
        if re.fullmatch(r"-?\d+", value):
            return int(value)
    except ValueError:
        pass
    # Try float
    try:
        if re.fullmatch(r"-?\d+\.\d+(?:[eE][+-]?\d+)?", value):
            return float(value)
    except ValueError:
        pass
    # Flat bracket list: [a, b, c]
    if value.startswith("[") and value.endswith("]"):
        import json as _json
        try:
            parsed = _json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except _json.JSONDecodeError:
            pass
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_coerce_scalar(part.strip()) for part in inner.split(",")]
    # Inline JSON object: { "key": value, ... }
    if value.startswith("{") and value.endswith("}"):
        import json as _json
        try:
            return _json.loads(value)
        except _json.JSONDecodeError:
            pass
    # Fallback: raw string
    return value


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]
