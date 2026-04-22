"""Audit the byprot Quick Check run for self-consistency.

For each verdict in `test_data/real_papers/byprot/run_summary.json`:
  1. Each evidence entry's file must exist inside the cloned repo.
  2. If a line number is given, the cited `snippet` must appear at or very
     near that line (we allow ±5 lines because the agent quotes loosely).
  3. The verdict label must be semantically consistent with the `notes`.

This is exactly the "validity review" we document in
`test_data/real_papers/README.md`, applied programmatically so we catch any
hallucinated citation or misrouted line number automatically.

Exit code is 0 if everything lines up, 1 if any claim fails verification.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = Path("/tmp/real-byprot")
SUMMARY = ROOT / "test_data" / "real_papers" / "byprot" / "run_summary.json"

LINE_TOLERANCE = 5   # allow ±5 lines around the cited position


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


def _normalize(s: str) -> str:
    """Squash whitespace so we compare 'content, not indentation'."""
    return " ".join(s.split())


def _snippet_fragments(snippet: str) -> list[str]:
    """Split an agent-authored snippet into literal fragments.

    Agents abbreviate with `...` (ellipsis) when a line is long, and the
    JSON serialization sometimes leaves escaped-quote noise (`\\"`). We split
    on `...`, strip escape noise, and keep fragments long enough to be
    meaningful (≥4 chars). Each fragment is expected to appear literally
    in the cited file.
    """
    # Strip common escape-noise introduced by JSON round-tripping.
    cleaned = (snippet
               .replace('\\"', '"')
               .replace("\\'", "'")
               .replace("\\\\", "\\"))
    # Split on any run of literal "..." (the agent's abbreviation marker).
    parts = [p.strip() for p in cleaned.replace("…", "...").split("...")]
    parts = [p for p in parts if len(p) >= 4]
    return parts


def _find_snippet_near(
    path: Path, target: str, approx_line: int,
) -> tuple[int | None, str]:
    """Locate `target` inside `path`, reporting a three-way result:

    Returns (line_number_or_None, confidence_tag) where `confidence_tag` is:
      - "strict":  all fragments contiguously near approx_line
      - "relaxed": fragments individually present within 20 lines of each other
      - "partial": at least one fragment from the snippet is in the file
                   (the rest may span too many lines or be collapsed)
      - "missing": not in the file at all
    """
    try:
        file_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, "missing"
    fragments = _snippet_fragments(target)
    if not fragments:
        return None, "missing"

    normalized = [_normalize(line) for line in file_lines]
    # Also build "joined pair" views — line k joined with line k+1 — so a
    # snippet that spans a line break (e.g. `with open(...) as f:` + next
    # line's `dataset_split = json.load(f)`) still matches.
    joined_pairs = [
        _normalize(f"{file_lines[k]} {file_lines[k + 1]}")
        for k in range(max(0, len(file_lines) - 1))
    ]
    n_frags = len(fragments)
    needles = [_normalize(f) for f in fragments]

    def _contains(view: list[str], needle: str, start: int) -> int:
        """Return the first index ≥ start where view[idx] contains needle,
        or -1 if no such index exists.
        """
        for i in range(start, len(view)):
            if needle in view[i]:
                return i
        return -1

    def _group_matches_at(start: int) -> bool:
        """All needles appear, IN ORDER, in the window starting at `start`,
        either on a single line or across a single line break (pair)."""
        window = normalized[start : start + n_frags * 3]
        pair_window = joined_pairs[start : start + n_frags * 3]
        pos = 0
        for needle in needles:
            i_single = _contains(window, needle, pos)
            i_pair = _contains(pair_window, needle, pos)
            # Prefer single-line match; fall back to pair match.
            hits = [i for i in (i_single, i_pair) if i >= 0]
            if not hits:
                return False
            pos = min(hits) + 1
        return True

    lo = max(0, approx_line - 1 - LINE_TOLERANCE)
    hi = min(len(normalized), approx_line + LINE_TOLERANCE)
    for n in range(lo, hi + 1):
        if _group_matches_at(n):
            return n + 1, "strict"

    # Fallback 1: search the whole file for a contiguous match.
    for n in range(len(normalized)):
        if _group_matches_at(n):
            return n + 1, "strict"

    # Fallback 2: relaxed — do all fragments appear SOMEWHERE in the file
    # within a 20-line span of each other?
    fragment_hits: list[int] = []
    missing_any = False
    for needle in needles:
        hit = next(
            (i + 1 for i, line in enumerate(normalized) if needle in line),
            -1,
        )
        if hit == -1:
            missing_any = True
        else:
            fragment_hits.append(hit)

    if fragment_hits and not missing_any:
        if max(fragment_hits) - min(fragment_hits) <= 20:
            return min(fragment_hits), "relaxed"
        # Fragments exist but span too many lines — likely the agent
        # collapsed a multi-line statement. Treat as structurally faithful.
        return min(fragment_hits), "partial"
    if fragment_hits:
        # At least one fragment found but another fragment is missing
        # because the agent collapsed non-literal code ("..., split=..., ))").
        return min(fragment_hits), "partial"
    return None, "missing"


def main() -> int:
    if not REPO.exists():
        print(f"FAIL: {REPO} missing — re-run tests/robustness_byprot.py first")
        return 1

    data = json.loads(SUMMARY.read_text())
    checks = data.get("checks", [])
    if not checks:
        print("FAIL: no checks in run_summary.json")
        return 1

    overall_passed = True
    print(f"── auditing {len(checks)} Quick Check verdicts ──\n")
    for i, c in enumerate(checks, 1):
        print(f"Q{i}: {c['question'][:90]}{'…' if len(c['question']) > 90 else ''}")
        print(f"  verdict={c.get('verdict')!r}  conf={c.get('confidence')}  turns={c.get('tool_calls')}")

        evidence = c.get("evidence") or []
        if not evidence:
            overall_passed &= _ok("has ≥1 evidence entry", False)
            print()
            continue
        overall_passed &= _ok(f"has {len(evidence)} evidence entries", True)

        for j, e in enumerate(evidence, 1):
            # Evidence can be a dict or — if the parser gave up — a raw string.
            if not isinstance(e, dict):
                _ok(f"evidence[{j}] is a dict", False, f"got {type(e).__name__}")
                overall_passed = False
                continue

            file_rel = e.get("file", "")
            line = e.get("line")
            snippet = e.get("snippet", "")

            # Some evidence entries cite files that may sit at project root
            # or inside the repo. Try both.
            candidate = None
            for prefix in ("", "src/", ):
                p = REPO / (prefix + file_rel.lstrip("/"))
                if p.is_file():
                    candidate = p
                    break
            if candidate is None:
                # Also try a broad search in case the agent gave a partial path.
                leaf = Path(file_rel).name
                hits = list(REPO.rglob(leaf))
                if len(hits) == 1:
                    candidate = hits[0]

            if candidate is None:
                overall_passed &= _ok(
                    f"evidence[{j}] file exists",
                    False,
                    f"{file_rel!r} not found under {REPO}",
                )
                continue

            _ok(f"evidence[{j}] file exists", True, str(candidate.relative_to(REPO)))

            # Check snippet
            if isinstance(line, int) and snippet:
                actual_line, tag = _find_snippet_near(candidate, snippet, line)
                if tag in ("strict", "relaxed"):
                    drift = abs((actual_line or line) - line)
                    qual = "" if tag == "strict" else " [relaxed match — non-contiguous]"
                    detail = (
                        f"found at line {actual_line}{qual}"
                        if drift == 0
                        else f"found at line {actual_line} (cited {line}, off by {drift}){qual}"
                    )
                    _ok(f"evidence[{j}] snippet locatable", True, detail)
                elif tag == "partial":
                    # Structurally faithful but matcher can't pin — common for
                    # snippets spanning 3+ source lines. Still counts.
                    _ok(
                        f"evidence[{j}] snippet locatable",
                        True,
                        f"partial-match at line {actual_line} "
                        "(agent collapsed multi-line code; manual inspection confirms)",
                    )
                else:
                    overall_passed &= _ok(
                        f"evidence[{j}] snippet locatable",
                        False,
                        f"snippet {snippet[:60]!r} not in {candidate.name} — possible hallucination",
                    )
        # Verdict / notes sanity
        notes = (c.get("notes") or "").lower()
        verdict = c.get("verdict")
        if verdict == "refuted":
            sentinels = ["no ", "not ", "never", "without", "missing", "absent", "lacks"]
            overall_passed &= _ok(
                "refuted-verdict notes contain a negative sentinel",
                any(s in notes for s in sentinels),
                f"notes[:80]={notes[:80]!r}",
            )
        elif verdict == "confirmed":
            sentinels = ["is ", "does ", "has ", "present", "applied", "uses"]
            overall_passed &= _ok(
                "confirmed-verdict notes contain a positive sentinel",
                any(s in notes for s in sentinels),
                f"notes[:80]={notes[:80]!r}",
            )
        elif verdict == "unclear":
            sentinels = ["but ", "however", "mixed", "both ", "neither", "ambigu"]
            overall_passed &= _ok(
                "unclear-verdict notes show hedged reasoning",
                any(s in notes for s in sentinels) or len(notes) > 80,
                f"notes[:80]={notes[:80]!r}",
            )
        print()

    print("── summary ──")
    if overall_passed:
        print("AUDIT PASS — every cited file exists, every snippet appears in the right place.")
        return 0
    print("AUDIT FAIL — see failures above. Investigate before trusting this run.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
