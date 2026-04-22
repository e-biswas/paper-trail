# Backend — Run Orchestrator (agent.py)

## Purpose

The run orchestrator wraps `claude_agent_sdk.query()` for the **conductor** agent and owns envelope emission over the WebSocket. Deep Investigation and Quick Check share this module; they differ only in prompt, turn budget, tool allowlist, and which subagents the conductor is allowed to invoke.

The conductor does not do every task itself — it delegates to **subagents** (see [subagents.md](subagents.md)). Paper ingestion is deterministic and runs before the SDK loop (see [paper_ingester.md](paper_ingester.md)). Code execution goes through the **Sandbox** (see [sandbox.md](sandbox.md)).

The markdown-section parser lives in a separate module, `server/parser.py`, so it can be tested independently against the fixtures in `test_data/parser/`.

## Status

`TODO` · last updated 2026-04-21

## Public interface

Exposes one async generator:

```python
# server/agent.py

from typing import AsyncIterator, Literal
from dataclasses import dataclass

Mode = Literal["investigate", "check"]

@dataclass
class RunConfig:
    mode: Mode
    run_id: str
    repo_path: str              # absolute path to pre-staged repo
    paper_url: str | None = None
    repo_slug: str | None = None  # "owner/repo", for PR targeting
    question: str | None = None   # Quick Check only

async def run_agent(config: RunConfig) -> AsyncIterator[dict]:
    """
    Yields envelope-shaped dicts ready to JSON-encode and send over WS.
    Every yielded dict matches the schema in docs/integration.md.

    The caller (FastAPI handler) is responsible for:
    - JSON-encoding and sending over WebSocket
    - Assigning `seq` (monotonic) and `ts`
    - Catching exceptions and emitting a final `error` + `session_end`
    """
```

The handler code is roughly:

```python
async for event in run_agent(config):
    event["seq"] = next_seq()
    event["ts"] = now_iso()
    event["run_id"] = config.run_id
    await ws.send_json(event)
```

## Implementation notes

### SDK invocation

```python
from claude_agent_sdk import query, ClaudeAgentOptions

options = ClaudeAgentOptions(
    model="claude-opus-4-7",
    system_prompt=load_prompt(config.mode),    # investigator.md or quick_check.md
    allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep", "WebFetch"],
    mcp_servers=build_mcp_servers(),           # github MCP; see mcp_config.md
    cwd=config.repo_path,                       # agent operates inside the cloned repo
    max_turns=30 if config.mode == "investigate" else 8,
    include_partial_messages=True,             # fine-grained streaming
    # NO extended thinking — it suppresses live streaming events
)

async for message in query(prompt=build_prompt(config), options=options):
    ...
```

`include_partial_messages=True` is required — without it we only get whole-turn messages and the Hypothesis Board looks dead for seconds at a time. Verify Day 1.

### Event forwarding

Two layers emitted per SDK message:

1. **Raw passthrough.** Every `content_block_delta` / `tool_use` / `tool_result` gets wrapped in a `raw_text_delta` / `tool_call` / `tool_result` envelope and yielded immediately. This drives the Tool Stream pane and keeps the UI feeling live.

2. **Parsed high-level events.** As text deltas accumulate, the parser (below) matches completed `## <Section>` markdown blocks and emits structured events (`hypothesis`, `check`, etc.).

### Stateful markdown-section parser

The investigator prompt instructs the agent to use an exact set of section headers. The parser watches the text stream:

```
## Claim: ...              → claim_summary
## Hypothesis N: <name>    → hypothesis (rank=N; body parsed for confidence + reason)
## Check: <hypothesis>     → check
## Finding: ...            → finding
## Verdict: ...            → verdict
## Fix applied: ...        → fix_applied
## Metric delta: ...       → metric_delta
## Dossier — <section>: ...→ dossier_section (section ∈ fixed set of 5)
## PR opened: <url>        → pr_opened  (backup; real one also comes from MCP tool_result)
## Aborted: ...            → aborted
```

Implementation approach:

- Maintain a rolling text buffer per run.
- Split on `\n## ` to find section boundaries. A section is "complete" when the next `\n## ` appears OR when `session_end` is about to fire.
- For each completed section, run a type-specific regex/YAML-frontmatter parser to extract fields (confidence, rank, etc.). System prompt enforces a minimal structured body inside each section (key: value lines) to make parsing robust.

### Tool call extraction

For `tool_use` / `tool_result` content blocks in the SDK stream, emit `tool_call` / `tool_result` envelopes directly with `{id, name, input, output, is_error, duration_ms}`. The parser does not need to see these — they are first-class.

### PR creation

The investigator prompt ends with an instruction to call `mcp__github__create_pull_request`. When the server sees that `tool_result`, it extracts the returned URL and emits `pr_opened`.

### Quick Check mode

Same runtime, different prompt (`quick_check.md`), different `max_turns=8`. Parser runs; only emits `tool_call`, `tool_result`, `quick_check_verdict`, `session_end`, `error`. The Quick Check prompt instructs the agent to emit exactly one `## Verdict` block in a strict YAML-like schema:

```
## Verdict:
verdict: confirmed | refuted | unclear
confidence: 0.0–1.0
evidence:
  - file: path/to/file
    line: 47
    snippet: "code excerpt"
  - ...
notes: "one-line summary"
```

### Cost tracking

`query()` yields a final `ResultMessage` with `total_cost_usd` and `num_turns`. The handler propagates these into `session_end.data`.

### Error handling

- If `query()` raises, emit `error` envelope with `code="agent_exception"` + exception message, then `session_end` with `ok=false`.
- If the agent hits `max_turns` without emitting `## Verdict`, wrap the final assistant message and emit `aborted` with `reason="turn_cap"`, then `session_end`.

## How to verify (end-to-end)

### Test data

- Muchlinski fixture staged at `/tmp/muchlinski-demo` with imputation-before-split bug.
- Expected agent trajectory: identify leakage on line 47 of `prepare_data.py`, fix by moving imputation into a `Pipeline`, re-run eval, see RF AUC drop from ~0.85 to ~0.72.

### Steps

1. Run `uv run python -m server.agent --demo muchlinski` (small harness script that prints envelopes to stdout).
2. Pipe output through `jq` to confirm every line is valid JSON.
3. Confirm the sequence of `type` values matches (at minimum):
   - `session_start` → `claim_summary` → ≥3 × `hypothesis` → ≥1 × `check` → ≥1 × `finding` → `verdict` → `fix_applied` → `metric_delta` → 5 × `dossier_section` → `pr_opened` → `session_end`
4. Confirm `session_end.data.ok == true` and `cost_usd < 5`.
5. Confirm `pr_opened.data.url` resolves to a real PR.

### Expected failure modes and how to diagnose

- **No events at all.** `include_partial_messages` likely dropped or model mis-configured. Check SDK options.
- **Tool calls appear but no parsed events.** Prompt is not emitting `## <Section>` headers as specified. Fix the prompt.
- **Parser emits garbage.** Section body didn't match expected schema. Tighten the prompt's required body format.
- **`pr_opened` never fires.** GitHub MCP failed — check `mcp_config.md` troubleshooting.

## Planned — abort + live cost meter (see TASKS D5.X-abort)

A client-triggered cancel path and a cumulative-cost stream, both depending on
contract edits documented in [../integration.md](../integration.md). Summary of
the agent-side work:

- **Cancel path.** The server's WS receive loop (see
  [server.md](server.md)) accepts a `{"type": "stop"}` frame mid-run. It
  cancels the `asyncio.Task` wrapping `run_agent(config)`. The orchestrator
  catches `asyncio.CancelledError`, flushes any open phase via the existing
  `_PhaseTracker`, and emits one terminal `session_end` with
  `stop_reason: "user_abort"` and `ok: false`. No additional envelopes
  after that. Double-emission is prevented by the existing guard that makes
  `session_end` the last yield.
- **Cost accumulation.** `query()` yields token-usage information on every
  `AssistantMessage` / `ToolResultBlock`. Track a running `total_cost_usd`
  alongside the phase tracker; emit a `cost_update` envelope no more often
  than once per 750 ms to avoid flooding the socket. The running value is
  also copied onto the final `session_end.data.cost_usd`, preserving the
  current contract for end-of-run cost.

Verification: run Muchlinski, cancel at ~15 s; expect `session_end` with
`stop_reason="user_abort"`, `ok=false`, and `cost_usd > 0`. Run to completion
and confirm monotonically non-decreasing `cost_update` values up to the final
`session_end.cost_usd`.

## Known gaps / corner cases

Findings from the Apr 22 audit pass. Every BLOCKER entry must be fixed
(or explicitly annotated "won't fix for demo") before the D6 submission.

- **BLOCKER — `raw_text_delta` events promised but never emitted.**
  Contract lists `raw_text_delta` ([../integration.md:102-107](../integration.md))
  but `server/agent.py:622-667` extracts `TextBlock`s and parses them
  without wrapping each delta in an envelope. Breaks the documented
  "toggle raw text in Tool Stream" debug mode.
  Fix sketch: after appending to the buffer, emit
  `{"type": "raw_text_delta", "data": {"text": block.text}}` before
  running the parser.
- **BLOCKER — Quick Check `quick_check_verdict` parsed but not yielded.**
  `parser.py` emits `quick_check_verdict` but `server/agent.py:618-702`
  never forwards it in check mode, so the happy-path Quick Check returns
  no verdict.
  Fix sketch: include it in the set of parser events the orchestrator
  yields, alongside the investigate-mode events.
- **BLOCKER — no synthesized `aborted` when SDK stops at `max_turns`.**
  When the agent fails to write `## Aborted:` and the loop exhausts at
  `max_turns=30`, no `aborted` envelope fires; contract says the server
  must synthesize one (`reason="turn_cap"`).
  Fix sketch: after the SDK loop exits, check `total_turns` and parser
  state; if terminal and no aborted event was emitted, yield one before
  the `session_end`.
- **MAJOR — duplicate `session_end` on exception paths.**
  `server/agent.py:359-381` emits `session_end` on exception; the
  `server/main.py` WS handler also wraps the generator and can emit a
  second one. Contract says `session_end` is always the final event,
  exactly once.
  Fix sketch: agent owns `session_end`; the wrapper should only emit one
  if the generator aborted before yielding anything.
- **MAJOR — client disconnect leaks the `run_agent` task.**
  `server/main.py:164-167` logs the disconnect and returns, but the
  generator task keeps running and burning tokens until the SDK call
  completes or times out.
  Fix sketch: wrap the generator in an `asyncio.Task` and `.cancel()` it
  from the WS disconnect handler.
- **MAJOR — `assistant_buffer` is O(n)-re-parsed on every delta.**
  `server/agent.py:611-651` accumulates the full markdown text and
  re-runs the parser after every text delta. Unbounded in memory; O(n²)
  in the tail of a verbose 30-turn run.
  Fix sketch: track a last-parsed offset and parse only the suffix; cap
  the buffer at ~1 MB and drop the oldest section-safe boundary.
- **MINOR — `session_context` splicing may re-parse stale section headers.**
  Prior-run summaries are pasted into the current prompt
  (`server/agent.py:550, 583-591`). If they include section headers
  identical to the new run, the parser sees them twice.
  Fix sketch: sanitize pasted markdown by stripping `^##` prefixes, or
  fence the context block as code.

## Open questions / deferred

- Retries on transient SDK errors: not needed at MVP. Let errors propagate; user retries from UI.
- Resumable runs (mid-stream reconnect): `DEFERRED`.
- Parser implemented as regex vs proper markdown AST: start with regex, revisit if brittleness emerges.
