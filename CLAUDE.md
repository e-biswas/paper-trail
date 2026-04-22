# CLAUDE.md — Project Instructions for Paper Trail

This file is auto-loaded by Claude Code at the start of every session. Read it first. It tells you what the project is, the rules you work under, and where to look for more detail.

---

## What this project is

**Paper Trail** is the user's entry for Cerebral Valley's "Built with Opus 4.7" Claude Code hackathon (Apr 21–26, 2026). It is a **Claude-powered agent + web dashboard** that investigates why an ML paper's published result does not reproduce from its public repo, and opens an evidence-backed GitHub PR with the minimal fix.

The product has **two modes** and both are required for MVP:

1. **Deep Investigation** — paste a paper URL + a GitHub repo URL, watch the agent generate ranked hypotheses live, run discriminating checks via tool use, converge on a root cause, fix it, re-run the eval, and open a real GitHub PR with a scientific audit dossier.
2. **Quick Check** — a chat-style sidebar where a researcher asks targeted verification questions ("is this imputation fit on train only?") and gets a bounded, cited, fast answer. This reframes the product from "autonomous agent" to **"verification intern for research engineers."**

The 4-act demo narrative (Quick Check warmup → Deep Investigation → PR artifact → optional medical-AI encore) lives in [docs/pitch.md](docs/pitch.md).

---

## Doc map — where to find what

| Topic | File |
|---|---|
| Full plan, risks, day-by-day | *(developer's local planning doc outside the repo — not part of the submission)* |
| Task status (source of truth for progress) | [TASKS.md](TASKS.md) |
| Build journals (Claude's + developer's) | [diary/claude.md](diary/claude.md), [diary/eb.md](diary/eb.md). Update both when something notable happens. |
| Public project overview | [README.md](README.md) |
| **Event contract between backend and frontend** | [docs/integration.md](docs/integration.md) — **load-bearing, frozen after Day 1** |
| Backend overview + module index | [docs/backend/README.md](docs/backend/README.md) |
| Backend module plans | [docs/backend/agent.md](docs/backend/agent.md), [subagents.md](docs/backend/subagents.md), [prompts.md](docs/backend/prompts.md), [paper_ingester.md](docs/backend/paper_ingester.md), [sandbox.md](docs/backend/sandbox.md), [server.md](docs/backend/server.md), [mcp_config.md](docs/backend/mcp_config.md), [fixtures.md](docs/backend/fixtures.md) |
| Frontend overview + module index | [docs/frontend/README.md](docs/frontend/README.md) |
| Frontend module plans | [app_shell.md](docs/frontend/app_shell.md), [hypothesis_board.md](docs/frontend/hypothesis_board.md), [tool_stream.md](docs/frontend/tool_stream.md), [dossier.md](docs/frontend/dossier.md), [quick_check.md](docs/frontend/quick_check.md), [parser_and_state.md](docs/frontend/parser_and_state.md), [styling.md](docs/frontend/styling.md) |
| Submission narrative + Future Vision (pitch to giants) | [docs/pitch.md](docs/pitch.md) |
| Original idea memo | [ideas.md](ideas.md) |

---

## Working rules — non-negotiable

These rules are agreed with the user. Violating them wastes their time.

### 1. Test every functionality end-to-end the moment it's written

- No "I wrote it, moving on." Every implementation step ends with a verification pass.
- **Produce test data. Execute. Compare actual vs expected.** If they diverge, fix before the next step.
- Every module doc has a mandatory **"How to verify (end-to-end)"** section. Follow it; update it if the procedure changes.

### 2. Keep docs in sync with code state

- When a module goes `TODO → WIP`, update its Status line and the entry in [TASKS.md](TASKS.md) in the same edit.
- Same for `WIP → DONE` and `DONE → REVIEWED`.
- `TASKS.md` is the single source of truth for progress. If it's not in `TASKS.md`, it doesn't exist.
- **Append to the diaries** ([diary/claude.md](diary/claude.md) and [diary/eb.md](diary/eb.md)) when something notable happens — a pushback, a decision, a surprise, a workaround. Keep entries to 1–3 sentences. Dated. Never rewrite history — if an entry turns out wrong, add a later entry noting so.

### 3. The integration contract is frozen after Day 1

- [docs/integration.md](docs/integration.md) defines the event schema the backend emits and the frontend consumes.
- If we want to change an event shape: update `integration.md` **first**, then update both sides in the same commit.
- Never ship a backend event shape that isn't in the contract.

### 4. Scope discipline

- Day 4 EOD is the hard scope freeze. Anything not done by then doesn't ship.
- Do not add features not in the plan without asking the user.
- If something is out of scope but tempting, note it in the module's **"Open questions / deferred"** section and move on.

### 5. Secrets hygiene

- Never commit `.env`. `.env.example` only.
- GitHub PAT and Anthropic API key live in `.env` locally.
- If you spot a real secret in the repo, tell the user immediately.

---

## Tooling conventions

- **Python ≥ 3.11**, managed with **`uv`** (not pip/poetry). `uv sync`, `uv run ...`.
- **Node ≥ 20**, `npm` (not yarn/pnpm). Frontend is **React + Vite + TypeScript + Tailwind + shadcn/ui**.
- **Agent SDK:** `claude-agent-sdk` (Python package). Subagent delegation via the SDK's `Task` tool.
- **Server:** FastAPI + `uvicorn` + native WebSocket support.
- **Paper ingestion:** arXiv URLs → `arxiv` Python package + arXiv LaTeX source. Arbitrary PDFs → `docling` (IBM Research). Results cached by URL hash.
- **Sandbox:** `Sandbox` abstraction with `LocalSandbox` as the only MVP backend (executes inside a staged `/tmp/<fixture>-demo/` working dir). `E2BSandbox` is a documented slot, not implemented. No cloud spend allowed.
- **GitHub integration:** official GitHub MCP server (`@modelcontextprotocol/server-github`), run as subprocess by the agent SDK.
- **Model:** Opus 4.7 (`claude-opus-4-7`). **Regular streaming only** — extended thinking may suppress live stream events.
- **Ports:** server on `8080`, Vite dev on `5173`.

---

## Repo layout (authoritative)

```
paper-trail/
├── CLAUDE.md        ← you are here
├── README.md
├── TASKS.md
├── ideas.md
├── pyproject.toml
├── .env.example
├── docs/
│   ├── integration.md         ← event contract
│   ├── pitch.md
│   ├── backend/
│   └── frontend/
├── server/          ← Python code
│   ├── main.py                  # FastAPI + WS endpoints
│   ├── agent.py                 # Run orchestrator (conductor SDK call + envelope emission)
│   ├── parser.py                # markdown-section → envelope events
│   ├── mcp_config.py            # GitHub MCP
│   ├── subagents/               # Code Auditor, Experiment Runner, Paper Reader
│   ├── papers/                  # arXiv API + docling ingester + cache
│   ├── sandbox/                 # Sandbox interface + LocalSandbox
│   └── prompts/
│       ├── investigator.md
│       ├── quick_check.md
│       └── failure_classes.md
├── web/             ← React code
│   └── src/...
└── demo/
    ├── primary/     ← Muchlinski fixture
    └── backup/      ← ISIC fixture
```

---

## Token / cost budgets (hackathon has $500 in API credits)

| Operation | Budget | Hard cap in code |
|---|---|---|
| One Deep Investigation run | ≤ $5 | `max_turns=30` |
| One Quick Check | ≤ $1 | `max_turns=8`, target ≤60s wall-clock |
| Daily demo rehearsal | ≤ $30 | — |

If a run exceeds its turn cap, the agent must emit a `## Aborted` section with reason. The frontend renders this distinctly.

---

## Demo invariants — things that MUST be true for the submission to work

These are the behaviors judges will see. If any of these fail, the demo fails.

1. **Hypothesis Board populates within 30s** of starting a Deep Investigation with ≥3 ranked hypotheses.
2. **Tool Stream** shows real tool calls (file reads, grep results, bash output) happening in real time — not a progress spinner.
3. **Agent converges on the root cause** on the primary fixture (Muchlinski: imputation-before-split) with confidence >80% within ~3 minutes.
4. **Before/after metric delta** is reported in the Dossier after the fix is applied. No delta = not done.
5. **Dossier populates all five canonical sections** in order: *Claim tested · Evidence gathered · Root cause · Fix applied · Remaining uncertainty*. An incomplete dossier is a failed run.
6. **Real GitHub PR** opens on the bot's fork; link visible in the UI; PR body contains the full 5-section dossier; diff is minimal (<50 LOC).
7. **Quick Check** answers a canned question in <30s with a `confirmed` | `refuted` | `unclear` verdict + at least one code citation.
8. Works on the ISIC backup fixture too (generalization proof).

---

## Forbidden actions

- Don't run actual model training runs during investigation. The agent does only small, cheap discriminating checks.
- Don't commit secrets. Ever.
- Don't let Quick Check scope-creep into a general chatbot. Fixed turn cap, fixed output schema.
- Don't change event shapes without updating [docs/integration.md](docs/integration.md) first.
- Don't add cloud dependencies (e2b, Modal, Coreweave, etc.) — zero-spend constraint. `LocalSandbox` only for MVP.
- Don't add a database, auth layer, or persistence. Single-process, single-session.
- Don't use extended thinking mode — it suppresses live stream events (verify Day 1).
- Don't bypass the `Sandbox` abstraction to run code directly. All repo execution goes through it so we can swap backends without touching subagents.

---

## Start-of-session checklist (for Claude)

When a new session opens on this repo:

1. Read `CLAUDE.md` (this file).
2. Read [TASKS.md](TASKS.md) to see what's WIP / blocked / next.
3. Check git status if there's a git repo (there isn't yet).
4. Ask the user what they want to work on if not obvious, and match their intent against `TASKS.md`.
5. Update `TASKS.md` when you start and finish work.
