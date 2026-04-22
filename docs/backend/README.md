# Backend — Overview

## Purpose

Python service that runs the Claude Agent SDK, streams the agent's reasoning and tool use to the frontend over WebSocket, and drives GitHub PR creation via the MCP server. Two WebSocket endpoints, two agent modes (Deep Investigation, Quick Check), one shared tool setup.

## Status

`TODO` · last updated 2026-04-21

## Module index

| Module | File | Status | Responsibility |
|---|---|---|---|
| Run orchestrator | [agent.md](agent.md) | `TODO` | Wraps `claude_agent_sdk.query()` for the conductor; forwards raw SDK events; owns envelope emission |
| Markdown-section parser | [agent.md](agent.md#stateful-markdown-section-parser) (shipped in `server/parser.py`) | `TODO` | Extracts `## Hypothesis`, `## Check`, etc. from the text stream and emits high-level events |
| Subagents | [subagents.md](subagents.md) | `TODO` | Conductor + specialized subagents (Code Auditor, Experiment Runner, Paper Reader). Delegation via SDK `Task` tool. |
| Prompts | [prompts.md](prompts.md) | `TODO` | System prompts: `investigator.md`, `quick_check.md`, `failure_classes.md` + per-subagent prompts |
| Paper ingester | [paper_ingester.md](paper_ingester.md) | `TODO` | arXiv URLs → raw LaTeX via arXiv API; arbitrary PDFs → docling; cached by URL hash |
| Sandbox | [sandbox.md](sandbox.md) | `TODO` | `Sandbox` interface + `LocalSandbox` (MVP backend). All repo code execution goes through this. |
| Server | [server.md](server.md) | `TODO` | FastAPI app; WS endpoints `/ws/investigate` and `/ws/check`; env loading; lifecycle |
| MCP config | [mcp_config.md](mcp_config.md) | `TODO` | GitHub MCP server subprocess config, auth, tool allowlist |
| Fixtures | [fixtures.md](fixtures.md) | `DONE` (2026-04-21) | Demo repo staging: Muchlinski primary, ISIC backup. Both verified E2E. |

## Shared conventions

### Directory layout (authoritative)

```
server/
├── main.py                 ← FastAPI app entrypoint
├── agent.py                ← Run orchestrator (conductor query() + envelope emission)
├── parser.py               ← markdown-section → envelope events
├── mcp_config.py           ← GitHub MCP setup
├── env.py                  ← env loading + validation
├── subagents/
│   ├── __init__.py
│   ├── base.py             ← shared subagent result type
│   ├── code_auditor.py     ← read-only code inspection tasks
│   ├── experiment_runner.py ← executes code in a Sandbox
│   └── paper_reader.py     ← summarizes paper claims from an ingested Paper
├── papers/
│   ├── __init__.py
│   ├── models.py           ← Paper dataclass (title, abstract, sections, claims, ...)
│   ├── ingester.py         ← arXiv API + docling dispatch
│   ├── arxiv_fetcher.py    ← raw LaTeX from arXiv API
│   ├── pdf_parser.py       ← docling wrapper
│   └── cache.py            ← on-disk cache keyed by URL hash
├── sandbox/
│   ├── __init__.py
│   ├── base.py             ← Sandbox interface
│   └── local.py            ← LocalSandbox (MVP)
└── prompts/
    ├── investigator.md
    ├── quick_check.md
    ├── failure_classes.md
    └── subagents/
        ├── code_auditor.md
        ├── experiment_runner.md
        └── paper_reader.md
```

### Python conventions

- Python ≥ 3.11, managed by `uv`. Do not use `pip` or `poetry`.
- Type hints everywhere. `from __future__ import annotations` in every file.
- `async` throughout the request path. No blocking calls in WebSocket handlers.
- Structured logging via stdlib `logging` at `INFO`; `DEBUG` guarded behind `LOG_LEVEL` env var.
- No custom framework abstractions. FastAPI + SDK directly.

### Event shapes

Every outbound WebSocket message MUST match the envelope in [../integration.md](../integration.md). If you need a new event type, update `integration.md` first, then both sides.

### Cost discipline

- Deep Investigation: `max_turns=30`, target ≤ $5 per run.
- Quick Check: `max_turns=8`, target ≤ $1 per run.
- Every `session_end` event MUST include `cost_usd` and `total_turns` for budget tracking.

### Testing philosophy (per CLAUDE.md working rule #1)

Every backend module has a **"How to verify (end-to-end)"** section. When you finish implementing a module, run its verification steps, compare actual vs expected, and only mark `DONE` once actual matches expected.

## How to verify (end-to-end) — whole backend

After all modules land:

1. `uv sync` succeeds with no warnings.
2. `uv run uvicorn server.main:app --reload` boots on `:8080` with no tracebacks.
3. Open `ws://localhost:8080/ws/investigate` with a WebSocket client (e.g. `websocat`).
4. Send `{"type":"start","run_id":"test","config":{"paper_url":"...","repo_path":"/tmp/muchlinski","repo_slug":"bot/muchlinski"}}`.
5. Observe `session_start` → several `hypothesis` → `check` → `finding` → `verdict` → `fix_applied` → `metric_delta` → `dossier_section` × 5 → `pr_opened` → `session_end`.
6. Real PR URL in `pr_opened.data.url` opens and shows the fix + dossier.
7. Repeat on `/ws/check` with a canned question; expect exactly one `quick_check_verdict` then `session_end`.

## Known gaps index

Quick index of the Apr 22 audit findings per module. See each module's
**Known gaps / corner cases** section for severity, file:line, and fix
sketches.

- [agent.md](agent.md#known-gaps--corner-cases) — `raw_text_delta`
  never emitted; `quick_check_verdict` orphaned; no synthesized
  `aborted` on `max_turns`; duplicate `session_end`; disconnect task
  leak; buffer re-parse cost; `session_context` header collisions.
- [server.md](server.md#known-gaps--corner-cases) — no stop-frame
  loop yet; silent send failures; no receive timeout; no heartbeat;
  handshake leaves sockets in CLOSE_WAIT; CORS/WS origin drift; input
  size limits; per-run structured logging.
- [subagents.md](subagents.md#known-gaps--corner-cases) — subagent
  turn budgets don't roll up; raw `Bash` in Experiment Runner;
  validator drops malformed entries silently; venv python rewrite
  is brittle; prompt loading is blocking disk I/O.
- [sandbox.md](sandbox.md#known-gaps--corner-cases) — no memory
  limits; symlink escape; process-group kill race; silent truncation.
- [paper_ingester.md](paper_ingester.md#known-gaps--corner-cases) —
  cache key doesn't invalidate on arxiv v1→v2; PDF URL not validated;
  docling cold start blocks concurrent ingest; arxiv ID regex too
  lenient.
- [mcp_config.md](mcp_config.md#known-gaps--corner-cases) — silent
  missing `GITHUB_TOKEN`; PR-fail-after-dossier ambiguity; no MCP
  subprocess recovery; branch name collision.
- [prompts.md](prompts.md#known-gaps--corner-cases) — schema not
  enforced by worked example; Quick Check tool-chain cap advisory;
  failure-class specificity uneven; validator tone-vs-rigor conflict.
- [fixtures.md](fixtures.md#known-gaps--corner-cases) — `reset.sh`
  swallows `gh pr close` errors; init_demo_repos swallows bad-scope
  force-push failures; token scrubbing not trap-protected;
  `dev.sh` skips re-stage if `/tmp/*-demo` exists; replay streams
  hand-authored; ground-truth doesn't pin sklearn/numpy.

Gate-check for D6 submission: every entry tagged **BLOCKER** above
must either have a fix landed or a deliberate "won't fix for demo"
annotation (see `TASKS.md D5.0-audit-gaps`).

## Open questions / deferred

- Replay/cassette mode for testing the frontend without hitting the API. `DEFERRED` to stretch.
- Rate-limiting the WS endpoints. Not needed; single-user demo.
- Structured tracing (OpenTelemetry). `DEFERRED` post-hackathon.
