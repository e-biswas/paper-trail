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

Conductor + subagents share the Deep Investigation budget of 50 turns / $5. A typical run: conductor uses ~12 turns, spawns 2–3 Code Auditor subagents (4 turns each = 12), 1 Experiment Runner (2 turns), 1 Paper Reader (2 turns), 1 Patch Generator (4 turns), 1 Metric Extractor (2 turns) = ~34 turns total. Room for a ratify/retry round on the fix.

### Error handling

Subagent failures surface via `SubagentResult(ok=False, error="...")`. The conductor treats a failed subagent like any other negative tool result — it emits a `## Finding` with the failure and continues. **A failed subagent does NOT crash the run.**

### Future slots (not in MVP)

- **Benchmark Evaluator** subagent — evaluates the fix against a canonical benchmark slice (for heavier-compute Deep Investigation in the future-vision section).
- **Per-domain subagent packs** — Medical Imaging Auditor, NLP Auditor, etc. Each plugs in via the same `SubagentResult` interface.

## Planned — Patch Generator subagent (see TASKS D5.X-patchgen)

A read-only subagent that converts a ratified hypothesis + supporting
findings into a unified diff, without touching the working tree. The
conductor then applies (or rejects) the diff via the sandbox, which
keeps fix application auditable and makes retries cheap.

- **Role.** Given `hypothesis_id`, a summary of supporting evidence,
  and the repo layout, propose the smallest diff that addresses the
  hypothesis.
- **Tool allowlist.** `Read`, `Grep`, `Glob`. No `Edit`, `Write`, or
  `Bash` — the subagent never mutates files or runs code. Prevents
  half-applied fixes from polluting the sandbox on retry.
- **Output schema.** Emit exactly one `## Patch:` block:
  ```
  ## Patch:
  hypothesis_id: h1
  rationale: "Move imputation inside a sklearn Pipeline so fit_transform runs on train only."
  target_files:
    - prepare_data.py
  diff: |
    ```diff
    --- a/prepare_data.py
    +++ b/prepare_data.py
    @@ ...
    - imputer.fit(df)
    + pipeline = Pipeline([("impute", IterativeImputer()), ("rf", RandomForestClassifier())])
    ...
    ```
  ```
- **Upstream handoff (conductor).** The conductor extracts `diff`,
  runs `git apply --check` inside the sandbox; on success, `git apply`
  followed by the re-eval flow. On `--check` failure, the conductor
  spawns **one** retry round with the error output included as extra
  context. A second failure surfaces as `## Aborted: reason=patch_invalid`.
- **Turn budget.** 4 turns, `max_turns=4`. Much lower than Code Auditor
  because the task is more focused.
- **Prompt.** Lives at `server/prompts/subagents/patch_generator.md`
  (see [prompts.md](prompts.md)).

Verification: run Deep Investigation on Muchlinski; after the `## Verdict:`
block, confirm a `Task` invocation with `agent="patch_generator"`, a
`## Patch:` block in its result, and a subsequent `git apply` that
changes `prepare_data.py` with <50 LOC.

## Planned — Metric Extractor subagent (see TASKS D5.X-metric)

A tool-free subagent that normalizes raw eval-script stdout into a
canonical `MetricResult` struct the dossier can render without free-
form string parsing.

- **Role.** Consume the stdout of the Experiment Runner's eval, pick
  out the reported metric(s), and return a typed payload. Handles
  numbered tables, sklearn `classification_report`, custom `METRIC_JSON:`
  lines, and one-off prints like `AUC = 0.85`.
- **Tool allowlist.** None. Pure prompt over text → structured output.
- **Output schema.** Emit exactly one `## Metric:` block per metric:
  ```
  ## Metric:
  name: "AUC"
  value: 0.72
  confidence_interval: [0.68, 0.76]   # optional; null if the eval didn't report one
  split: "test"                        # "train" | "val" | "test" | "other"
  context: "RandomForest, Muchlinski fixture, 5-fold CV"
  ```
- **Turn budget.** 2 turns, `max_turns=2`.
- **Contract impact.** The conductor's `metric_delta` event now carries
  structured `before` / `after` as full `MetricResult` dicts instead of
  free-form strings. This is a documented contract change (see
  [../integration.md](../integration.md)).
- **Prompt.** Lives at `server/prompts/subagents/metric_extractor.md`.

Verification: feed in the Muchlinski broken-baseline stdout; expect
`AUC` extracted with `value=0.85, split="test"` and the fixed stdout
yielding `0.72`. Assert `metric_delta` in the resulting event stream
has both `before` and `after` matching the extracted structs.

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

## Known gaps / corner cases

- **MAJOR — subagent turn budgets don't roll up into conductor's
  `max_turns=50`.** `server/subagents/code_auditor.py:68` sets its own
  cap; the conductor can spawn five auditors in parallel and exceed the
  parent budget.
  Fix sketch: track cumulative subagent turns in the conductor; refuse
  new `Task` calls when `parent_used + child_max > parent_budget`.
- **MAJOR — Experiment Runner uses raw `Bash`.** `allowed_tools=["Bash"]`
  at `server/subagents/experiment_runner.py:93` means the subagent can
  run `pip install`, `curl`, or anything else; the prompt-level
  prohibition is advisory. Fix sketch: swap in a `sandboxed_bash` MCP
  wrapper that enforces the allowed-commands list at tool boundary.
- **MINOR — Validator silently drops malformed entries.**
  `server/subagents/validator.py:179-191` defensively filters entries
  without the required `label` / `mark` fields; the caller gets a
  partial report with no warning. Fix sketch: log
  `"dropped N of M checks due to malformed schema"` when the count
  mismatches.
- **MINOR — Venv `python` rewrite is brittle.**
  `server/subagents/experiment_runner.py:29-48` rewrites only the
  leading `python` / `python3` token; `bash -c "python foo"` escapes
  unrewritten. Document the limitation and prefer absolute-path commands.
- **MINOR — Prompt loading is synchronous disk I/O per invocation.**
  `server/subagents/base.py:93-103` re-reads the prompt file every
  call. Cache at module-load time, or use `asyncio.to_thread()`.

## Open questions / deferred

- Subagent caching: if the same audit question is asked twice in one run, skip the second call. `DEFERRED`.
- Subagent retry on transient failure. `DEFERRED`; let the conductor handle it.
- Per-subagent cost accounting in the envelope stream: the overall `session_end` already rolls up total cost; per-subagent granularity is `DEFERRED` to post-hackathon.
