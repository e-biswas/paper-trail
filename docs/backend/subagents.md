# Backend — Subagents

## Purpose

Specialized worker agents the conductor delegates to, instead of one monolithic agent handling every task. Each subagent has a narrow remit, a focused prompt, its own tool allowlist, and returns a structured result. Delegation happens via the Claude Agent SDK's `Task` tool, which spawns a subagent with a fresh context window.

## Status

`TODO` · last updated 2026-04-21

## Why this shape

The alternative (one agent, one prompt, every tool) works but has three problems at hackathon scale:

1. **Context bloat** — a long Deep Investigation fills the context with tool output; by the end the conductor is reasoning about a paper + repo code + eval stdout + dossier state, all at once. Subagents keep the conductor's context focused on orchestration.
2. **No specialization** — the same prompt that generates ranked hypotheses is also the prompt that parses a paper PDF and the prompt that runs a sandbox command. Those are different jobs with different failure modes.
3. **No obvious parallelism** — the conductor can spawn 2 Code Auditor checks in parallel on different hypotheses, but only if they're cleanly separable calls.

Subagents = specialization + context isolation + natural parallel dispatch points.

**Not multi-agent with inter-agent messaging.** The conductor is the only source of truth for run state; subagents are stateless workers. No message bus, no peer-to-peer traffic.

## Public interface

Each subagent is a function with a clear input/output contract:

```python
# server/subagents/base.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

@dataclass
class SubagentResult:
    ok: bool
    summary: str                  # one-liner the conductor can paste into its narrative
    payload: dict[str, Any]       # structured details (varies by subagent)
    cost_usd: float
    duration_ms: int
    error: str | None = None
```

Each subagent module exports an async function:

```python
# server/subagents/code_auditor.py
async def audit(
    repo_path: Path,
    question: str,               # natural-language "what to inspect"
    hints: list[str] | None = None,  # file paths or grep patterns the conductor suggests
) -> SubagentResult:
    ...
```

Under the hood, each subagent runs its OWN short `claude_agent_sdk.query()` invocation with:
- a narrow system prompt (`prompts/subagents/<name>.md`)
- a narrow tool allowlist
- a small `max_turns` (typically 4–8)
- no MCP servers unless explicitly needed

### The three MVP subagents

| Subagent | Purpose | Tools allowed | Typical turns |
|---|---|---|---|
| **Code Auditor** | Read-only inspection. "Does prepare_data.py split before imputation?" Returns findings + file:line citations. | `Read`, `Glob`, `Grep` | 3–6 |
| **Experiment Runner** | Execute code inside the `Sandbox`. "Run `python src/eval.py` and return the METRIC_JSON line." Returns parsed metric payload. | `Bash` (routed through Sandbox) | 2–4 |
| **Paper Reader** | Summarize an already-ingested `Paper` into 1–3 sentences of claim text + a list of key methodological commitments. | No tools (pure prompt on Paper markdown) | 1–2 |

### How the conductor invokes them

The conductor's system prompt includes a short "delegation guide": when to call which subagent and what to include in the task description. The conductor delegates by calling the SDK's `Task` tool (or by direct Python function call, for non-LLM subagents like Paper Reader when there's no ambiguity to reason about).

Schematically:

```python
# pseudo-code inside server/agent.py
async def run_conductor(config):
    paper = await ingest_paper(config.paper_url)                      # not a subagent call (deterministic)
    paper_summary = await paper_reader.summarize(paper)               # subagent call
    async for event in sdk_query(
        prompt=build_conductor_prompt(config, paper_summary),
        system_prompt=load_prompt("investigator"),
        allowed_tools=["Read", "Grep", "Glob", "Edit", "Bash", "Task", "mcp__github__*"],
        mcp_servers=build_mcp_servers(),
    ):
        yield envelope(event)
```

The conductor's allowed toolset INCLUDES `Task`. When it invokes `Task(description="Audit prepare_data.py for split-before-impute", agent="code_auditor")`, the SDK spawns a sub-query using the Code Auditor's narrow prompt and tool set.

### Parallel dispatch

When the conductor has two independent discriminating checks to run (e.g., one for each top hypothesis), it spawns both via `Task` in the same turn. SDK handles them concurrently.

## Implementation notes

### Subagent prompts

All in `server/prompts/subagents/*.md`. Each must instruct its subagent to:
- Stay scoped to the task description; do not drift.
- Output a single structured result block at the end (so the conductor can parse it reliably).
- Cap tool calls at a reasonable number (the turn budget enforces a hard limit too).

### Result parsing

Each subagent ends its output with a fenced YAML block (or similar structured form) that the caller parses into `SubagentResult.payload`. The parser lives alongside the subagent module.

### Cost budgets

Conductor + subagents share the Deep Investigation budget of 30 turns / $5. A typical run: conductor uses ~10 turns, spawns 2–3 Code Auditor subagents (4 turns each = 12), 1 Experiment Runner (2 turns), 1 Paper Reader (2 turns) = ~26 turns total. Some headroom.

### Error handling

Subagent failures surface via `SubagentResult(ok=False, error="...")`. The conductor treats a failed subagent like any other negative tool result — it emits a `## Finding` with the failure and continues. **A failed subagent does NOT crash the run.**

### Future slots (not in MVP)

- **Benchmark Evaluator** subagent — evaluates the fix against a canonical benchmark slice (for heavier-compute Deep Investigation in the future-vision section).
- **Per-domain subagent packs** — Medical Imaging Auditor, NLP Auditor, etc. Each plugs in via the same `SubagentResult` interface.

## How to verify (end-to-end)

### Setup

Muchlinski fixture staged at `/tmp/muchlinski-demo` (already produced by `demo/primary/stage.sh`).

### Per-subagent smoke tests

1. **Code Auditor:** call `audit(repo_path=/tmp/muchlinski-demo, question="Is imputation fit on train only, or on the full dataframe?")`. Expected: `ok=True`, `summary` mentions line 28 of `prepare_data.py`, `payload` contains a list of evidence entries.
2. **Experiment Runner:** call `run(sandbox=LocalSandbox("/tmp/muchlinski-demo"), command="python src/eval.py")`. Expected: `ok=True`, `payload["metric"]` contains `{"AUC": {"rf": 0.9562, "lr": 0.8091}}`.
3. **Paper Reader:** feed in the markdown from `test_data/papers/muchlinski.md`. Expected: `summary` is a 1–3 sentence paraphrase of the paper's claim; `payload["claims"]` has at least one entry mentioning "RF > LR".

### Full-flow check (once conductor is wired up)

Deep Investigation on Muchlinski fixture should produce a transcript that includes:
- At least two `Task`-tool invocations (tool_call events with `name="Task"`)
- Each `tool_result` for those Tasks contains a `SubagentResult`-shaped payload
- The conductor reasons explicitly about the subagent findings in its `## Finding` blocks

## Open questions / deferred

- Subagent caching: if the same audit question is asked twice in one run, skip the second call. `DEFERRED`.
- Subagent retry on transient failure. `DEFERRED`; let the conductor handle it.
- Per-subagent cost accounting in the envelope stream: the overall `session_end` already rolls up total cost; per-subagent granularity is `DEFERRED` to post-hackathon.
