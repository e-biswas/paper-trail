"""Run orchestrator for Paper Trail.

Wraps `claude_agent_sdk.query()` for the conductor agent and yields envelope
events matching the schema in `docs/integration.md`.

Design:
- Load the real investigator / quick_check prompts at runtime.
- Splice the paper summary into the user prompt when `paper_url` points at a
  local test-data file. (Day 2 reads directly from disk; Day 3 adds the full
  arXiv + docling ingester.)
- Stream SDK messages, forwarding raw `tool_call` / `tool_result` envelopes
  immediately so the Tool Stream UI feels live.
- Accumulate assistant text into a buffer; after every AssistantMessage, re-run
  `server.parser.parse()` on the full buffer and emit any events that weren't
  emitted before (the parser naturally withholds incomplete sections since it
  requires the NEXT `## ...:` header to know a section has ended).
"""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from server.mcp_config import GITHUB_TOOL_ALLOWLIST, build_mcp_servers
from server.parser import parse as parse_markdown
from server.runs import RunMeta, get_store

log = logging.getLogger(__name__)

Mode = Literal["investigate", "check"]

# Turn budgets per mode (see CLAUDE.md "Token / cost budgets").
# Headroom-first: the conductor + 4 subagents need elbow room for the
# ratify/patch/retry flow; Quick Check needs enough steps for a two-round
# grep when the first pass misses the right file.
TURN_BUDGETS: dict[Mode, int] = {"investigate": 50, "check": 15}

# Cost ceilings. Set generously; caller can override via RunConfig.extras.
DEFAULT_BUDGETS_USD: dict[Mode, float] = {"investigate": 5.00, "check": 1.00}

# Models the user can pick from the UI. Keep aligned with `web/src/types.ts`.
ALLOWED_MODELS: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
)
DEFAULT_MODEL: str = "claude-opus-4-7"

# Per-million-token prices (USD) for in-flight cost estimates. The SDK's
# ResultMessage is authoritative at end-of-run; these are only used to drive
# the `cost_update` stream before the ResultMessage arrives. Approx Apr 2026.
_MODEL_PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    # model → (input_per_mtok, output_per_mtok)
    "claude-opus-4-7":           (15.0, 75.0),
    "claude-sonnet-4-6":          (3.0, 15.0),
    "claude-haiku-4-5-20251001":  (1.0,  5.0),
}

# Minimum spacing between cost_update emissions (seconds). Per integration.md
# contract: "no more than 1 emission per 750 ms".
_COST_UPDATE_MIN_INTERVAL_SEC = 0.75

# Tool allowlists per mode. Subagent delegation via `Task` is reserved for
# Day 3+; the Day-2 conductor does the investigation itself.
_INVESTIGATE_TOOLS: list[str] = [
    "Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch",
]
_CHECK_TOOLS: list[str] = ["Read", "Grep", "Glob"]


# ---------------------------------------------------------------------- #
# Config
# ---------------------------------------------------------------------- #


class ConfigError(ValueError):
    """Invalid RunConfig input from the WS start frame."""


@dataclass(frozen=True)
class RunConfig:
    mode: Mode
    run_id: str
    repo_path: Path | None = None
    paper_url: str | None = None
    repo_slug: str | None = None
    question: str | None = None
    session_id: str | None = None
    model: str = DEFAULT_MODEL
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def max_turns(self) -> int:
        return TURN_BUDGETS[self.mode]

    @property
    def max_budget_usd(self) -> float:
        override = self.extras.get("max_budget_usd")
        if isinstance(override, (int, float)) and override > 0:
            return float(override)
        return DEFAULT_BUDGETS_USD[self.mode]

    @classmethod
    def from_dict(cls, *, mode: Mode, run_id: str, raw: dict[str, Any]) -> "RunConfig":
        if not isinstance(raw, dict):
            raise ConfigError("config must be an object")

        repo_path_str = raw.get("repo_path")
        repo_path = Path(repo_path_str).resolve() if repo_path_str else None
        if repo_path is not None and not repo_path.exists():
            raise ConfigError(f"repo_path does not exist: {repo_path}")

        paper_url = raw.get("paper_url")
        question = raw.get("question")

        if mode == "investigate":
            if not repo_path:
                raise ConfigError("'investigate' mode requires a `repo_path`")
        elif mode == "check":
            if not question or not isinstance(question, str):
                raise ConfigError("'check' mode requires a `question` string")
            if not repo_path:
                raise ConfigError("'check' mode requires a `repo_path`")
        else:  # pragma: no cover
            raise ConfigError(f"unknown mode: {mode}")

        session_id = raw.get("session_id")
        if session_id is not None and not isinstance(session_id, str):
            raise ConfigError("session_id must be a string if provided")

        model_raw = raw.get("model")
        if model_raw is None:
            model = DEFAULT_MODEL
        elif not isinstance(model_raw, str):
            raise ConfigError("model must be a string if provided")
        elif model_raw not in ALLOWED_MODELS:
            raise ConfigError(
                f"model must be one of {ALLOWED_MODELS}, got {model_raw!r}",
            )
        else:
            model = model_raw

        user_prompt = raw.get("user_prompt")
        if user_prompt is not None and not isinstance(user_prompt, str):
            raise ConfigError("user_prompt must be a string if provided")

        reserved = {"repo_path", "paper_url", "repo_slug", "question",
                    "session_id", "model", "user_prompt"}
        extras = {k: v for k, v in raw.items() if k not in reserved}

        return cls(
            mode=mode,
            run_id=run_id,
            repo_path=repo_path,
            paper_url=paper_url,
            repo_slug=raw.get("repo_slug"),
            question=question,
            session_id=session_id,
            model=model,
            extras=extras,
        )


# ---------------------------------------------------------------------- #
# Prompt + paper loading
# ---------------------------------------------------------------------- #


_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _load_prompt(name: str) -> str:
    path = _PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def _build_investigator_system_prompt() -> str:
    """Render the investigator prompt with the failure-class taxonomy spliced in."""
    base = _load_prompt("investigator")
    taxonomy = _load_prompt("failure_classes")
    return base.replace("{{FAILURE_CLASSES}}", taxonomy)


def _build_quick_check_system_prompt() -> str:
    return _load_prompt("quick_check")


def _venv_python() -> Path | None:
    """Absolute path to the project venv's python, for `Bash` commands."""
    candidate = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


async def _load_paper_context(paper_url: str | None) -> str:
    """Return a paper summary to splice into the user prompt.

    Routes through `server.papers.ingest()` which dispatches between:
      - arXiv URLs (e.g. https://arxiv.org/abs/1603.05629) → arXiv API + docling
      - Arbitrary PDFs (local or remote) → docling
      - Local .md/.tex → read directly as markdown
    Results are cached on disk so repeated runs of the same URL are fast.
    Truncates large papers to 20K chars for the conductor's context.
    """
    if not paper_url:
        return "(no paper URL provided for this run)"
    url = paper_url.strip()
    try:
        from server.papers import ingest

        paper = await ingest(url)
    except ImportError as exc:
        log.warning("paper ingester not importable: %s; falling back to raw read", exc)
        return _load_paper_context_fallback(url)
    except Exception as exc:
        log.warning("paper ingest failed (%s); falling back to raw read", exc)
        return _load_paper_context_fallback(url)

    MAX_CHARS = 20_000
    body = paper.full_markdown
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + f"\n\n[... truncated; original was {len(paper.full_markdown)} chars ...]"
    return body


def _build_session_context_block(session_id: str | None, exclude_run_id: str) -> str:
    """Build a 'prior findings in this session' context block.

    Returns an empty string if there's no session or no prior runs.
    Otherwise returns a compact markdown summary of each prior run's verdict,
    fix, and PR, suitable for prepending to the user prompt so the conductor
    has continuity across turns in the same chat session.
    """
    if not session_id:
        return ""
    try:
        store = get_store()
        prior = [m for m in store.recent_verdicts_for_session(session_id, limit=5)
                 if m.run_id != exclude_run_id]
    except Exception as exc:
        log.warning("could not load session history: %s", exc)
        return ""
    if not prior:
        return ""

    lines: list[str] = [
        "## Prior context from this session",
        "",
        "Earlier turns in the SAME chat session with the user produced the findings",
        "below. Treat these as established facts you can reference. Do NOT re-investigate",
        "them from scratch unless the user explicitly asks.",
        "",
    ]
    for i, m in enumerate(prior, 1):
        lines.append(f"### Turn {i} — {m.mode} ({m.run_id})")
        if m.paper_url:
            lines.append(f"- paper: {m.paper_url}")
        if m.repo_path:
            lines.append(f"- repo: `{m.repo_path}`")
        if m.verdict_summary:
            conf = f" (confidence {m.verdict_confidence})" if m.verdict_confidence is not None else ""
            lines.append(f"- verdict{conf}: {m.verdict_summary}")
        if m.files_changed:
            lines.append(f"- files changed by agent: {m.files_changed}")
        for md in m.metric_deltas or []:
            lines.append(
                f"- metric delta: {md.get('metric')} {md.get('before')} → "
                f"{md.get('after')} ({md.get('context')})"
            )
        if m.pr_url:
            lines.append(f"- PR opened: {m.pr_url}")
        lines.append("")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _load_paper_context_fallback(url: str) -> str:
    """Last-resort raw-file read when the ingester isn't available."""
    p = Path(url)
    if p.exists():
        return p.read_text(encoding="utf-8")
    if url.startswith("file://"):
        p = Path(url[len("file://"):])
        if p.exists():
            return p.read_text(encoding="utf-8")
    return f"(could not load paper from {url})"


# ---------------------------------------------------------------------- #
# Entry point
# ---------------------------------------------------------------------- #


async def run_agent(config: RunConfig) -> AsyncIterator[dict[str, Any]]:
    """Yield envelope-shaped dicts for one run.

    Envelopes are persisted to the on-disk RunStore as they're emitted so
    artifact endpoints (dossier, diff, events) can serve them afterward.

    This function guarantees that EVERY completed path (success, exception,
    or empty stream) emits exactly one terminal `session_end` envelope —
    stalls are never allowed.
    """
    store = get_store()
    store.begin_run(
        run_id=config.run_id,
        mode=config.mode,
        session_id=config.session_id,
        config={
            "paper_url": config.paper_url,
            "repo_path": str(config.repo_path) if config.repo_path else None,
            "repo_slug": config.repo_slug,
            "question": config.question,
            "max_budget_usd": config.max_budget_usd,
            "model": config.model,
            "user_prompt": config.extras.get("user_prompt"),
        },
    )

    async def _emit(event: dict[str, Any]) -> None:
        """Side-effect: persist the envelope, update meta, then yield."""
        store.append_event(config.run_id, event)
        store.update_meta_from_event(config.run_id, event)

    key = os.environ.get("ANTHROPIC_API_KEY", "")
    use_stub = not key or key.lower() in {"stub", "fake", "test", ""}

    if use_stub:
        log.info("run_agent (stub) mode=%s — no real API key", config.mode)
        source = _run_stub(config)
    else:
        source = _run_sdk(config)

    phases = _PhaseTracker()
    session_ended = False
    run_start_mono = asyncio.get_event_loop().time()

    try:
        async for event in source:
            # Derive phase boundaries from observed events. Emitted BEFORE the
            # triggering event so the frontend timeline is naturally causal.
            for phase_ev in phases.observe(event):
                await _emit(phase_ev)
                yield phase_ev

            await _emit(event)
            yield event

            if event.get("type") == "session_end":
                session_ended = True
    except asyncio.CancelledError:
        # Client disconnect or parent task cancellation. We report this as
        # `user_abort` per the abort contract (see docs/integration.md —
        # "Planned — abort + cost stream"). The WS handler cancels this task
        # when the browser sends `{"type": "stop"}` or disconnects mid-run,
        # so both paths surface the same terminal reason to persistence.
        if not session_ended:
            for phase_ev in phases.flush():
                await _emit(phase_ev)
                yield phase_ev
            elapsed_ms = int((asyncio.get_event_loop().time() - run_start_mono) * 1000)
            end = {
                "type": "session_end",
                "data": {
                    "ok": False,
                    "stop_reason": "user_abort",
                    "total_turns": 0,
                    "cost_usd": 0.0,
                    "duration_ms": elapsed_ms,
                },
            }
            await _emit(end)
            yield end
        raise
    except Exception as exc:
        log.exception("run_agent path failed")
        for phase_ev in phases.flush():
            await _emit(phase_ev)
            yield phase_ev
        err = {"type": "error", "data": {"code": "agent_exception", "message": str(exc)}}
        await _emit(err)
        yield err
        elapsed_ms = int((asyncio.get_event_loop().time() - run_start_mono) * 1000)
        end = {
            "type": "session_end",
            "data": {
                "ok": False,
                "error": str(exc),
                "total_turns": 0,
                "cost_usd": 0.0,
                "duration_ms": elapsed_ms,
            },
        }
        await _emit(end)
        yield end
        session_ended = True
        return

    # Defensive: if source exhausted without session_end (SDK oddity, stub bug,
    # future iterator change), synthesize one so the client never hangs.
    if not session_ended:
        log.warning("run_agent source exhausted without session_end — synthesizing one")
        for phase_ev in phases.flush():
            await _emit(phase_ev)
            yield phase_ev
        elapsed_ms = int((asyncio.get_event_loop().time() - run_start_mono) * 1000)
        end = {
            "type": "session_end",
            "data": {
                "ok": False,
                "stop_reason": "source_exhausted_without_end",
                "total_turns": 0,
                "cost_usd": 0.0,
                "duration_ms": elapsed_ms,
            },
        }
        await _emit(end)
        yield end


# ---------------------------------------------------------------------- #
# Phase tracker
# ---------------------------------------------------------------------- #


# Ordered phase list. Each phase starts when a certain event type is first seen
# and ends when the next phase's trigger arrives (or on session_end / flush).
# The tracker emits `phase_start` and `phase_end` envelopes at those boundaries.
_PHASE_ORDER: list[tuple[str, set[str]]] = [
    # Start as soon as the agent emits anything structural, so the time
    # the model actually spends reasoning before hypotheses is attributed.
    ("hypotheses", {"claim_summary", "hypothesis"}),
    ("checks", {"check"}),
    ("verify", {"verdict", "fix_applied", "metric_delta"}),
    ("dossier", {"dossier_section"}),
    ("pr", {"pr_opened"}),
]


class _PhaseTracker:
    """Derive `phase_start` / `phase_end` envelopes from observed events.

    Side-effect-free; the caller decides when to emit the yielded events.
    """

    def __init__(self) -> None:
        self._current: str | None = None
        self._current_rank: int | None = None
        self._started_at_mono: float | None = None
        self._seen: set[str] = set()

    def observe(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        etype = event.get("type")
        if not etype:
            return []
        out: list[dict[str, Any]] = []

        # session_end closes any open phase — but the caller emits session_end
        # itself, so we only contribute the phase_end here.
        if etype == "session_end":
            out.extend(self._close_current())
            return out

        # Find which phase (if any) this event belongs to.
        target_phase: str | None = None
        target_rank: int | None = None
        for rank, (phase_name, triggers) in enumerate(_PHASE_ORDER):
            if etype in triggers:
                target_phase = phase_name
                target_rank = rank
                break

        if not target_phase or target_rank is None:
            return out

        # Monotone: never reopen a phase already seen, and never open an
        # earlier phase once a later one has opened. The agent sometimes
        # interleaves `fix_applied` / `dossier_section` — those go into the
        # currently-open phase (or none) instead of reopening.
        if target_phase in self._seen:
            return out
        if self._current_rank is not None and target_rank < self._current_rank:
            return out

        out.extend(self._close_current())
        self._current = target_phase
        self._current_rank = target_rank
        self._started_at_mono = asyncio.get_event_loop().time()
        self._seen.add(target_phase)
        out.append({"type": "phase_start", "data": {"phase": target_phase}})
        return out

    def flush(self) -> list[dict[str, Any]]:
        """Close any open phase. Called on exception / empty-stream paths."""
        return self._close_current()

    def _close_current(self) -> list[dict[str, Any]]:
        if not self._current or self._started_at_mono is None:
            return []
        duration_ms = int((asyncio.get_event_loop().time() - self._started_at_mono) * 1000)
        ev = {
            "type": "phase_end",
            "data": {"phase": self._current, "duration_ms": duration_ms},
        }
        self._current = None
        self._current_rank = None
        self._started_at_mono = None
        return [ev]


# ---------------------------------------------------------------------- #
# Stub path
# ---------------------------------------------------------------------- #


async def _run_stub(config: RunConfig) -> AsyncIterator[dict[str, Any]]:
    yield {
        "type": "claim_summary",
        "data": {"claim": f"(stub) {config.mode} run for repo at {config.repo_path}"},
    }
    await asyncio.sleep(0.1)
    yield {
        "type": "tool_call",
        "data": {
            "id": "stub-tool-1",
            "name": "Read",
            "input": {"file_path": str(config.repo_path or "<no-repo>") + "/src/prepare_data.py"},
        },
    }
    await asyncio.sleep(0.1)
    yield {
        "type": "tool_result",
        "data": {
            "id": "stub-tool-1",
            "name": "Read",
            "output": "(stub output — real agent will populate this)",
            "is_error": False,
            "duration_ms": 80,
        },
    }
    yield {
        "type": "session_end",
        "data": {"ok": True, "total_turns": 1, "cost_usd": 0.0, "duration_ms": 200},
    }


# ---------------------------------------------------------------------- #
# SDK path
# ---------------------------------------------------------------------- #


async def _run_sdk(config: RunConfig) -> AsyncIterator[dict[str, Any]]:
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
        UserMessage,
        query,
    )

    # ── Session memory: prior-turn context (if any) ───────────────────
    session_context = _build_session_context_block(config.session_id, config.run_id)

    # ── Assemble prompt ───────────────────────────────────────────────
    if config.mode == "check":
        system_prompt = _build_quick_check_system_prompt()
        allowed_tools = _CHECK_TOOLS
        user_prompt = (
            (session_context if session_context else "")
            + f"Question: {config.question}\n\n"
            + f"Repo path: {config.repo_path}\n\n"
            + "Inspect and emit one `## Verdict:` block per your contract."
        )
    else:
        system_prompt = _build_investigator_system_prompt()
        allowed_tools = _INVESTIGATE_TOOLS
        # Bracket paper ingestion with phase events so the UI timeline shows it.
        yield {"type": "phase_start", "data": {"phase": "paper_ingest"}}
        _paper_start_mono = asyncio.get_event_loop().time()
        paper_context = await _load_paper_context(config.paper_url)
        yield {
            "type": "phase_end",
            "data": {
                "phase": "paper_ingest",
                "duration_ms": int((asyncio.get_event_loop().time() - _paper_start_mono) * 1000),
            },
        }
        venv_py = _venv_python()
        py_hint = (
            f"\n\nNote: the project's Python interpreter is at `{venv_py}`. "
            "Use it when invoking Python scripts (e.g., `{venv_py} src/eval.py`) "
            "— it has sklearn/pandas/numpy installed. The system `python` does not."
        ).format(venv_py=venv_py) if venv_py else ""
        user_prompt = (
            (session_context if session_context else "")
            + "Paper context:\n\n"
            + "------------------\n"
            + f"{paper_context}\n"
            + "------------------\n\n"
            + f"Repo path: {config.repo_path}\n"
            + f"Repo slug: {config.repo_slug or '(not set — skip PR creation)'}\n"
            + f"{py_hint}\n\n"
            + "Begin the investigation per your operating contract."
        )

    mcp_servers = build_mcp_servers() if config.mode == "investigate" else {}
    effective_allowed = list(allowed_tools)
    if "github" in mcp_servers:
        effective_allowed.extend(GITHUB_TOOL_ALLOWLIST)

    options = ClaudeAgentOptions(
        model=config.model,
        system_prompt=system_prompt,
        allowed_tools=effective_allowed,
        cwd=str(config.repo_path) if config.repo_path else None,
        max_turns=config.max_turns,
        max_budget_usd=config.max_budget_usd,
        include_partial_messages=True,
        mcp_servers=mcp_servers,
    )

    # ── Stream messages + parser-diff ──────────────────────────────────
    assistant_buffer: list[str] = []
    emitted_parser_count = 0  # how many parser events we've already yielded

    started = asyncio.get_event_loop().time()
    total_turns = 0             # updated live on AssistantMessage
    total_cost = 0.0            # authoritative only after ResultMessage
    estimated_cost = 0.0        # best-effort in-flight estimate for cost_update
    last_cost_emit_mono = 0.0   # rate-limits cost_update to contract cadence
    last_emitted_cost = 0.0     # ensures cost_update monotonically non-decreasing
    emitted_aborted = False     # tracks whether a `## Aborted:` block already fired
    saw_terminal_parsed = False # verdict / quick_check_verdict seen?

    async for msg in query(prompt=user_prompt, options=options):
        if isinstance(msg, SystemMessage):
            continue

        if isinstance(msg, AssistantMessage):
            total_turns += 1
            text_added = False
            for block in msg.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        # Ensure each text chunk starts on a new line so
                        # `## Section:` headers aren't smooshed into the
                        # previous chunk's trailing content (which breaks the
                        # line-anchored parser).
                        if assistant_buffer and not assistant_buffer[-1].endswith("\n"):
                            assistant_buffer.append("\n")
                        assistant_buffer.append(block.text)
                        text_added = True
                        # Debug-only raw passthrough per integration.md contract.
                        yield {
                            "type": "raw_text_delta",
                            "data": {"text": block.text},
                        }
                elif isinstance(block, ToolUseBlock):
                    yield {
                        "type": "tool_call",
                        "data": {
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        },
                    }

            # Best-effort cost estimate from the cumulative usage dict
            # the SDK attaches to each AssistantMessage. The final value
            # from ResultMessage supersedes at end-of-run.
            est = _estimate_cost_usd(config.model, getattr(msg, "usage", None))
            if est is not None and est > estimated_cost:
                estimated_cost = est
            # Rate-limit cost_update to contract cadence. Must be monotone
            # non-decreasing per integration.md; we emit max(last_emitted,
            # estimate).
            now_mono = asyncio.get_event_loop().time()
            if now_mono - last_cost_emit_mono >= _COST_UPDATE_MIN_INTERVAL_SEC:
                last_cost_emit_mono = now_mono
                emit_cost = max(last_emitted_cost, estimated_cost)
                if emit_cost >= last_emitted_cost:
                    last_emitted_cost = emit_cost
                    yield {
                        "type": "cost_update",
                        "data": {
                            "total_usd": round(emit_cost, 4),
                            "turns": total_turns,
                        },
                    }

            if text_added:
                # Re-parse the FULL buffer; the parser is idempotent.
                events = parse_markdown("".join(assistant_buffer))
                if len(events) > emitted_parser_count:
                    for ev in events[emitted_parser_count:]:
                        etype = ev.get("type")
                        if etype == "aborted":
                            emitted_aborted = True
                        elif etype in ("verdict", "quick_check_verdict"):
                            saw_terminal_parsed = True
                        yield ev
                    emitted_parser_count = len(events)
            continue

        if isinstance(msg, UserMessage):
            for block in msg.content:
                if isinstance(block, ToolResultBlock):
                    yield {
                        "type": "tool_result",
                        "data": {
                            "id": block.tool_use_id,
                            "name": "tool",
                            "output": _stringify_tool_result(block.content),
                            "is_error": bool(getattr(block, "is_error", False)),
                            "duration_ms": 0,
                        },
                    }
            continue

        if isinstance(msg, ResultMessage):
            total_turns = int(getattr(msg, "num_turns", total_turns) or total_turns)
            total_cost = float(getattr(msg, "total_cost_usd", 0.0) or 0.0)
            duration_ms = int(getattr(msg, "duration_ms", 0) or 0)
            ok = not bool(getattr(msg, "is_error", False))
            sdk_stop_reason = getattr(msg, "stop_reason", None)

            # Final parser flush in case the agent's last chars never triggered
            # a re-parse (e.g. no following message).
            full_text = "".join(assistant_buffer)
            events = parse_markdown(full_text)
            for ev in events[emitted_parser_count:]:
                etype = ev.get("type")
                if etype == "aborted":
                    emitted_aborted = True
                elif etype in ("verdict", "quick_check_verdict"):
                    saw_terminal_parsed = True
                yield ev
            emitted_parser_count = len(events)

            # Final authoritative cost_update (one last tick so the UI
            # converges on the real number before session_end closes the pill).
            # Monotonic: never decrease below prior emissions, even if the
            # SDK's authoritative total is smaller than an early estimate.
            final_cost_usd = max(last_emitted_cost, total_cost)
            last_emitted_cost = final_cost_usd
            yield {
                "type": "cost_update",
                "data": {
                    "total_usd": round(final_cost_usd, 4),
                    "turns": total_turns,
                },
            }

            # Synthesize an `aborted` envelope when the SDK stopped because
            # of the turn cap without the agent writing `## Aborted:` AND
            # without a terminal verdict. Spec requires the server emit this
            # so the frontend can distinguish "ran out of budget" from "done".
            session_stop_reason: str | None = sdk_stop_reason
            looks_like_turn_cap = (
                isinstance(sdk_stop_reason, str)
                and "turn" in sdk_stop_reason.lower()
            )
            hit_turn_cap_silently = (
                (looks_like_turn_cap or total_turns >= config.max_turns)
                and not emitted_aborted
                and not saw_terminal_parsed
            )
            if hit_turn_cap_silently:
                yield {
                    "type": "aborted",
                    "data": {
                        "reason": "turn_cap",
                        "detail": (
                            f"Run exhausted {config.max_turns}-turn budget "
                            "without producing a verdict."
                        ),
                    },
                }
                emitted_aborted = True
                session_stop_reason = "turn_cap"
                ok = False

            # Optional debug dump of the conductor's raw markdown output.
            dump_path = os.environ.get("REPRO_DEBUG_DUMP")
            if dump_path:
                try:
                    Path(dump_path).write_text(full_text, encoding="utf-8")
                    log.info("wrote %d chars of raw agent text to %s", len(full_text), dump_path)
                except OSError as e:
                    log.warning("could not write debug dump: %s", e)

            end_data: dict[str, Any] = {
                "ok": ok,
                "total_turns": total_turns,
                # Final value MUST equal the last cost_update per contract.
                "cost_usd": round(final_cost_usd, 4),
                "duration_ms": duration_ms,
            }
            if session_stop_reason is not None:
                end_data["stop_reason"] = session_stop_reason
            yield {"type": "session_end", "data": end_data}
            return

    # Defensive fallback: SDK exhausted without ResultMessage.
    elapsed = int((asyncio.get_event_loop().time() - started) * 1000)
    events = parse_markdown("".join(assistant_buffer))
    for ev in events[emitted_parser_count:]:
        yield ev
    yield {
        "type": "session_end",
        "data": {
            "ok": True,
            "total_turns": total_turns,
            "cost_usd": round(total_cost or estimated_cost, 4),
            "duration_ms": elapsed,
        },
    }


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _estimate_cost_usd(model: str, usage: dict[str, Any] | None) -> float | None:
    """Rough cost estimate from the SDK's cumulative `usage` dict.

    The SDK attaches a cumulative usage dict to each `AssistantMessage`.
    We turn that into a dollar figure using a small per-model price table.
    Returns None when `usage` is missing or unusable; the caller falls back
    to the prior estimate. The final ResultMessage.total_cost_usd supersedes
    all of these — this is a best-effort in-flight number for the UI.
    """
    if not usage or not isinstance(usage, dict):
        return None
    pin, pout = _MODEL_PRICING_PER_MTOK.get(model, (15.0, 75.0))

    def _int(key: str) -> int:
        try:
            return int(usage.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = _int("input_tokens")
    output_tokens = _int("output_tokens")
    cache_create = _int("cache_creation_input_tokens")
    cache_read = _int("cache_read_input_tokens")
    # Cache-write is usually priced at 1.25× input; cache-read at 0.10×.
    effective_input = input_tokens + int(cache_create * 1.25) + int(cache_read * 0.10)
    return (effective_input * pin + output_tokens * pout) / 1_000_000.0


def _stringify_tool_result(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", item)))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)
