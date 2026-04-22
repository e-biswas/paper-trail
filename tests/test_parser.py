"""Golden tests for `server.parser`.

Each fixture in `test_data/parser/valid/*.md` has a matching
`test_data/parser/expected/*.jsonl` listing the events the parser should emit.

Invalid fixtures (`test_data/parser/invalid/*.md`) MUST NOT crash the parser
and SHOULD emit zero events (any malformed header/body is a skip).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.parser import parse

ROOT = Path(__file__).resolve().parent.parent
VALID_DIR = ROOT / "test_data" / "parser" / "valid"
EXPECTED_DIR = ROOT / "test_data" / "parser" / "expected"
INVALID_DIR = ROOT / "test_data" / "parser" / "invalid"


def _load_expected(path: Path) -> list[dict]:
    events = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        events.append(json.loads(line))
    return events


def _pairs():
    for md in sorted(VALID_DIR.glob("*.md")):
        expected = EXPECTED_DIR / (md.stem + ".jsonl")
        if expected.exists():
            yield md, expected


@pytest.mark.parametrize("md,expected_path", list(_pairs()), ids=lambda p: p.stem if isinstance(p, Path) else str(p))
def test_parser_matches_expected(md: Path, expected_path: Path) -> None:
    expected = _load_expected(expected_path)
    actual = parse(md.read_text())

    assert len(actual) == len(expected), (
        f"{md.name}: expected {len(expected)} events, got {len(actual)}\n"
        f"actual types: {[e['type'] for e in actual]}\n"
        f"expected types: {[e['type'] for e in expected]}"
    )

    for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
        assert a["type"] == e["type"], (
            f"{md.name}: event {i} type mismatch — got {a['type']}, want {e['type']}"
        )

        # Deep compare data dicts. For `markdown` fields (dossier_section),
        # we're lenient about exact whitespace since markdown rendering can
        # legitimately reformat.
        a_data = dict(a["data"])
        e_data = dict(e["data"])
        if a["type"] == "dossier_section":
            a_md = (a_data.pop("markdown", "") or "").strip()
            e_md = (e_data.pop("markdown", "") or "").strip()
            assert a_md == e_md, f"{md.name}: dossier_section[{i}] markdown differs"

        assert a_data == e_data, (
            f"{md.name}: event {i} ({a['type']}) data mismatch\n"
            f"  actual:   {a_data}\n"
            f"  expected: {e_data}"
        )


@pytest.mark.parametrize("path", list(INVALID_DIR.glob("*.md")), ids=lambda p: p.name)
def test_parser_invalid_fixture_does_not_crash(path: Path) -> None:
    events = parse(path.read_text())
    # No strict assertion on count; some invalid fixtures have partial valid
    # sections (e.g. missing_confidence.md has TWO valid events + one bad
    # hypothesis that must be dropped). The contract is: does not raise.
    assert isinstance(events, list)


def test_parser_empty_string() -> None:
    assert parse("") == []


def test_parser_bare_prose() -> None:
    prose = (INVALID_DIR / "bare_prose.md").read_text()
    assert parse(prose) == []


def test_parser_missing_confidence_skips_only_that_one() -> None:
    """Hypothesis 1 has no confidence (skip). Hypothesis 2 is well-formed
    (keep). Check with hypothesis_id + description is well-formed (keep).
    """
    text = (INVALID_DIR / "missing_confidence.md").read_text()
    events = parse(text)
    types = [e["type"] for e in events]
    # Hypothesis 2 + the Check should survive. Hypothesis 1 is dropped.
    assert "hypothesis" in types
    assert "check" in types
    hyps = [e for e in events if e["type"] == "hypothesis"]
    assert len(hyps) == 1
    assert hyps[0]["data"]["rank"] == 2
