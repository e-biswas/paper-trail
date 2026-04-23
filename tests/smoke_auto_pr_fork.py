"""Smoke test for the Auto-PR toggle and fork-first flow.

Covers the pure-logic surface without hitting GitHub:

- `_fork_slug_for` returns a bot-owned slug only when the upstream owner
  differs from `GITHUB_BOT_OWNER`, and returns None otherwise.
- `_build_pr_directive` produces the four documented shapes
  (no slug / auto_pr off / fork-first / bot-owned) with the right guidance.
- `RunConfig.from_dict` accepts `auto_pr: bool` and rejects non-bools.
- The GitHub MCP allowlist contains `fork_repository` and NO destructive
  tools (no `delete_*`, `merge_*`, `close_*`).
- The investigator system prompt mentions the fork-first mechanics + the
  `Auto PR: OFF` escape hatch.
- `/runs/{id}/push_pr` guards (unknown run_id, missing files_changed,
  missing repo_slug, prior PR) return the right HTTP status codes via
  FastAPI's TestClient — no MCP/network calls triggered on the rejection
  paths.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Force stub-mode — no real Anthropic API calls.
os.environ["ANTHROPIC_API_KEY"] = "stub"
os.environ.setdefault("GITHUB_BOT_OWNER", "paper-trail")

from server import agent as agent_mod
from server.agent import RunConfig, ConfigError, _build_pr_directive, _fork_slug_for
from server.mcp_config import GITHUB_TOOL_ALLOWLIST
from server.main import app
from server.runs import RunMeta, RunStore, get_store
import server.runs as runs_module


def _ok(label: str, predicate: bool, detail: str = "") -> bool:
    icon = "✓" if predicate else "✗"
    tail = f" — {detail}" if detail else ""
    print(f"  {icon} {label}{tail}")
    return predicate


# ---------------------------------------------------------------------- #
# Phases
# ---------------------------------------------------------------------- #


def _phase_fork_slug_helper() -> bool:
    print("── phase 1: _fork_slug_for() returns the right shape ──")
    passed = True
    passed &= _ok(
        "bot-owned upstream → None",
        _fork_slug_for("paper-trail/demo") is None,
    )
    passed &= _ok(
        "third-party upstream → bot-owner/repo fork slug",
        _fork_slug_for("muchlinski/civil-war-rf") == "paper-trail/civil-war-rf",
    )
    passed &= _ok(
        "case-insensitive owner match",
        _fork_slug_for("Paper-Trail/demo") is None,
    )
    passed &= _ok("falsy slug → None", _fork_slug_for(None) is None)
    passed &= _ok("malformed slug → None", _fork_slug_for("not-a-slug") is None)
    return passed


def _phase_pr_directive_shapes() -> bool:
    print("── phase 2: _build_pr_directive() covers all four shapes ──")
    passed = True
    # No upstream — silent skip.
    no_slug = _build_pr_directive(repo_slug=None, fork_slug=None, auto_pr=True)
    passed &= _ok("no slug directive mentions n/a", "Auto PR: n/a" in no_slug)

    # Auto off — STOP with no mutation.
    off = _build_pr_directive(
        repo_slug="paper-trail/demo", fork_slug=None, auto_pr=False,
    )
    passed &= _ok("auto_pr=False says OFF", "Auto PR: OFF" in off)
    passed &= _ok(
        "auto_pr=False forbids create_pull_request call",
        "Do NOT call `mcp__github__create_pull_request`" in off,
    )

    # Bot-owned upstream — no fork step.
    bot = _build_pr_directive(
        repo_slug="paper-trail/demo", fork_slug=None, auto_pr=True,
    )
    passed &= _ok("bot-owned says 'no fork step needed'", "no fork step needed" in bot)

    # Fork-first — full three-step flow.
    fork = _build_pr_directive(
        repo_slug="muchlinski/civil-war-rf",
        fork_slug="paper-trail/civil-war-rf",
        auto_pr=True,
    )
    passed &= _ok("fork-first mentions fork_repository", "fork_repository" in fork)
    passed &= _ok(
        "fork-first shows cross-fork head format",
        "paper-trail:<branch>" in fork,
    )
    passed &= _ok(
        "fork-first names both slugs",
        "muchlinski/civil-war-rf" in fork and "paper-trail/civil-war-rf" in fork,
    )
    return passed


def _phase_runconfig_auto_pr_field() -> bool:
    print("── phase 3: RunConfig parses auto_pr boolean safely ──")
    # Investigate needs a real path; use this project's root.
    repo = str(Path(__file__).resolve().parent.parent)
    passed = True

    default_on = RunConfig.from_dict(
        mode="investigate", run_id="r1",
        raw={"repo_path": repo, "repo_slug": "paper-trail/demo"},
    )
    passed &= _ok("default auto_pr=True", default_on.auto_pr is True)

    explicit_off = RunConfig.from_dict(
        mode="investigate", run_id="r2",
        raw={"repo_path": repo, "repo_slug": "muchlinski/civil-war-rf", "auto_pr": False},
    )
    passed &= _ok("explicit auto_pr=False stored", explicit_off.auto_pr is False)

    try:
        RunConfig.from_dict(
            mode="investigate", run_id="r3",
            raw={"repo_path": repo, "auto_pr": "yes"},
        )
        passed &= _ok("non-bool rejected", False, "should have raised ConfigError")
    except ConfigError:
        passed &= _ok("non-bool auto_pr rejected", True)
    return passed


def _phase_allowlist_invariants() -> bool:
    print("── phase 4: MCP allowlist is additive-only + has fork_repository ──")
    passed = True
    passed &= _ok(
        "fork_repository in allowlist",
        "mcp__github__fork_repository" in GITHUB_TOOL_ALLOWLIST,
    )
    banned_substrings = ("__delete_", "__merge_", "__close_", "__update_pull_request")
    leaks = [t for t in GITHUB_TOOL_ALLOWLIST if any(b in t for b in banned_substrings)]
    passed &= _ok(
        "no destructive tools in allowlist",
        not leaks,
        f"leaks={leaks}" if leaks else "",
    )
    return passed


def _phase_investigator_prompt_mentions_fork_flow() -> bool:
    print("── phase 5: investigator.md documents fork + auto-off ──")
    p = Path(__file__).resolve().parent.parent / "server" / "prompts" / "investigator.md"
    txt = p.read_text(encoding="utf-8")
    passed = True
    passed &= _ok("mentions 'Auto PR: OFF'", "Auto PR: OFF" in txt)
    passed &= _ok("mentions fork-first mode", "fork-first mode" in txt)
    passed &= _ok(
        "says cross-fork head is bot-owner:<branch>",
        "<bot-owner>:<branch>" in txt,
    )
    passed &= _ok(
        "points at fork_repository call",
        "mcp__github__fork_repository" in txt,
    )
    return passed


def _phase_push_pr_endpoint_guards() -> bool:
    print("── phase 6: /runs/{id}/push_pr guards reject ill-formed requests ──")
    client = TestClient(app)
    passed = True

    # Unknown run_id → 404.
    r = client.post("/runs/does-not-exist/push_pr")
    passed &= _ok("unknown run_id → 404", r.status_code == 404, f"got {r.status_code}")

    # Seed a Quick Check run → mode guard should reject with 400.
    store = get_store()
    tmp_meta = RunMeta(
        run_id="check-guard",
        mode="check",
        session_id="s-guard",
        config={},
        created_at="2026-04-23T00:00:00Z",
        finished_at=None,
    )
    store._save_meta(tmp_meta)
    r = client.post("/runs/check-guard/push_pr")
    passed &= _ok("Quick Check run → 400", r.status_code == 400, f"got {r.status_code}")

    # Investigate with no files_changed → 409.
    empty = RunMeta(
        run_id="empty-inv",
        mode="investigate",
        session_id="s-guard",
        config={},
        created_at="2026-04-23T00:00:00Z",
        finished_at=None,
        repo_slug="paper-trail/demo",
    )
    store._save_meta(empty)
    r = client.post("/runs/empty-inv/push_pr")
    passed &= _ok(
        "investigate run w/o files_changed → 409",
        r.status_code == 409,
        f"got {r.status_code}",
    )

    # Prior PR → 409.
    with_pr = RunMeta(
        run_id="already-pr",
        mode="investigate",
        session_id="s-guard",
        config={},
        created_at="2026-04-23T00:00:00Z",
        finished_at=None,
        repo_slug="paper-trail/demo",
        files_changed=["src/x.py"],
        pr_url="https://github.com/paper-trail/demo/pull/1",
    )
    store._save_meta(with_pr)
    r = client.post("/runs/already-pr/push_pr")
    passed &= _ok(
        "prior PR → 409",
        r.status_code == 409,
        f"got {r.status_code}",
    )

    # Missing repo_slug → 409.
    no_slug = RunMeta(
        run_id="no-slug",
        mode="investigate",
        session_id="s-guard",
        config={},
        created_at="2026-04-23T00:00:00Z",
        finished_at=None,
        files_changed=["src/x.py"],
    )
    store._save_meta(no_slug)
    r = client.post("/runs/no-slug/push_pr")
    passed &= _ok(
        "no repo_slug → 409",
        r.status_code == 409,
        f"got {r.status_code}",
    )
    return passed


def main() -> int:
    saved_store = runs_module._STORE
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="paper-trail-fork-smoke-"))
    runs_module._STORE = RunStore(root=tmp)

    try:
        p1 = _phase_fork_slug_helper(); print()
        p2 = _phase_pr_directive_shapes(); print()
        p3 = _phase_runconfig_auto_pr_field(); print()
        p4 = _phase_allowlist_invariants(); print()
        p5 = _phase_investigator_prompt_mentions_fork_flow(); print()
        p6 = _phase_push_pr_endpoint_guards(); print()

        if all([p1, p2, p3, p4, p5, p6]):
            print("AUTO-PR + FORK SMOKE PASS")
            return 0
        print("AUTO-PR + FORK SMOKE FAIL")
        return 1
    finally:
        runs_module._STORE = saved_store
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
