# Integration Contract — Backend ↔ Frontend Event Schema

## Status

`TODO` · last updated 2026-04-21

This document is **load-bearing**. Both backend and frontend must implement this contract exactly as specified. It is **frozen after Day 1** — further changes require editing this file first, then both sides in the same commit.

---

## Purpose

Define the transport, message envelopes, and event types that flow between the Python backend and the React frontend. This is the single source of truth for the wire format.

---

## Transport

- **Protocol:** WebSocket (plain, not wss in dev; terminated by FastAPI).
- **Encoding:** UTF-8 JSON, one message per WebSocket frame.
- **Connection lifecycle:** client opens → sends `start` → server streams events → sends `session_end` → server closes.

## Endpoints

Backend exposes two WebSocket endpoints. Both share the envelope format; the event types that appear differ.

| Endpoint | Mode | Turn cap | Typical duration |
|---|---|---|---|
| `ws://localhost:8080/ws/investigate` | Deep Investigation | 30 | 2–5 min |
| `ws://localhost:8080/ws/check` | Quick Check | 8 | 10–60 s |

---

## Opening handshake

**Client → server (first frame, both endpoints):**

```jsonc
{
  "type": "start",
  "run_id": "uuid-v4-string",       // client-generated; echoed in every server event
  "config": {
    // Deep Investigation:
    "paper_url": "https://arxiv.org/abs/...",
    "repo_path": "/absolute/path/to/cloned/repo",   // pre-staged; server does not clone
    "repo_slug": "owner/repo",                        // for PR targeting
    // OR, Quick Check:
    "question": "Is imputation fit on train only?",
    "repo_path": "/absolute/path/to/cloned/repo",

    // Optional, both modes:
    "session_id": "s-abcd1234",        // groups chat turns; inferred from the ws session if absent
    "model": "claude-opus-4-7",         // one of: claude-opus-4-7, claude-sonnet-4-6, claude-haiku-4-5-20251001
    "max_budget_usd": 5.0               // upper bound on cost for this single run
  }
}
```

**Server → client (first frame back):**

```jsonc
{
  "type": "session_start",
  "run_id": "...",
  "ts": "2026-04-21T18:30:00Z",
  "seq": 0,
  "data": { "mode": "investigate" | "check" }
}
```

If config is invalid, server immediately sends an `error` frame and closes.

---

## Envelope format (every server → client message)

```jsonc
{
  "type": "<event-type>",
  "run_id": "uuid",
  "ts": "ISO-8601 timestamp",
  "seq": 42,              // monotonic per-run sequence, starts at 0 on session_start
  "data": { ... }         // type-specific payload, see below
}
```

Frontend MUST ignore unknown `type` values without erroring. This allows the backend to add new event types without breaking older frontends.

---

## Event types

There are two layers of events:

1. **Raw events** — direct passthrough of Claude Agent SDK messages. Useful for debugging, the Tool Stream pane, and future instrumentation.
2. **Parsed high-level events** — emitted by the server's markdown-section parser as structured sections (`## Hypothesis N:`, `## Check:`, etc.) complete in the assistant's text stream. These feed the Hypothesis Board, Dossier, and Verdict panes directly.

Frontend reducer routes high-level events to the correct pane; it may use raw events for live tool-call rendering.

### Raw events

| `type` | When emitted | `data` shape |
|---|---|---|
| `raw_text_delta` | Every `text_delta` from the SDK stream | `{ "text": "..." }` |
| `tool_call` | When the agent starts a tool invocation | `{ "id": "toolu_...", "name": "Read", "input": { ... } }` |
| `tool_result` | When a tool invocation returns | `{ "id": "toolu_...", "name": "Read", "output": "...", "is_error": false, "duration_ms": 120 }` |
| `thinking` | If extended thinking is on (it isn't, but reserved) | `{ "text": "..." }` |

### High-level parsed events (Deep Investigation)

Emitted when the server's parser detects a completed `## <Section>` block in the assistant's text stream. Parser is stateful (see [backend/agent.md](backend/agent.md) for implementation details).

| `type` | Emitted when agent writes... | `data` shape |
|---|---|---|
| `claim_summary` | Opening summary of the paper's claim | `{ "claim": "string (1-3 sentences)" }` |
| `hypothesis` | `## Hypothesis N: <name>` block completes | `{ "id": "h1", "rank": 1, "name": "Imputation-before-split leakage", "confidence": 0.72, "reason": "string" }` |
| `hypothesis_update` | A prior `## Hypothesis N:` has updated confidence after a finding | `{ "id": "h1", "confidence": 0.91, "reason_delta": "string" }` |
| `check` | `## Check: <hypothesis>` block completes | `{ "id": "c1", "hypothesis_id": "h1", "description": "string", "method": "string" }` |
| `finding` | `## Finding` block completes | `{ "id": "f1", "check_id": "c1", "result": "string", "supports": ["h1"], "refutes": [] }` |
| `verdict` | `## Verdict` block completes | `{ "hypothesis_id": "h1", "confidence": 0.92, "summary": "string" }` |
| `fix_applied` | Agent has `Edit`-ed files and re-run the eval | `{ "files_changed": ["prepare_data.py"], "diff_summary": "string" }` |
| `metric_delta` | Before/after metric comparison from re-run eval | `{ "metric": "AUC", "before": 0.85, "after": 0.72, "baseline": 0.74, "context": "RF" }` |
| `dossier_section` | One of the 5 dossier sections completes | `{ "section": "claim_tested" \| "evidence_gathered" \| "root_cause" \| "fix_applied" \| "remaining_uncertainty", "markdown": "..." }` |
| `pr_opened` | GitHub MCP successfully returned a PR URL | `{ "url": "https://github.com/...", "number": 42, "title": "string" }` |
| `validity_report` | Validator subagent finished auditing a completed Deep Investigation. **NOT emitted during the WS run itself** — the frontend fetches it on demand via `POST /runs/{id}/validate`, which returns the same payload shape synchronously. | `{ "overall": "strong"\|"acceptable"\|"weak"\|"unreliable", "summary": "...", "confidence": 0.xx, "checks": [{ "label": "hypothesis_coverage"\|"evidence_quality"\|"fix_minimality"\|"causal_link"\|"alternative_explanations"\|"uncertainty_honesty"\|"suggested_followup", "mark": "pass"\|"warn"\|"fail", "note": "..." }, ...] }` |
| `phase_start` | A coarse investigation phase begins. Emitted once per phase. | `{ "phase": "paper_ingest"\|"hypotheses"\|"checks"\|"verify"\|"dossier"\|"pr" }` |
| `phase_end` | The current phase closes (next phase starting, or session ending). | `{ "phase": "paper_ingest"\|"hypotheses"\|"checks"\|"verify"\|"dossier"\|"pr", "duration_ms": 12345 }` |
| `aborted` | Agent hit turn cap or emitted `## Aborted` | `{ "reason": "turn_cap" \| "error" \| "agent_requested", "detail": "string" }` |
| `session_end` | Run completed (success or failure) | `{ "ok": true, "total_turns": 14, "cost_usd": 3.21, "duration_ms": 187000 }` |
| `error` | Unrecoverable error | `{ "code": "string", "message": "string" }` |

#### Phase semantics

Phases are derived, lightweight annotations — they help the UI show *what's happening right now* and build an inline timeline once the run ends. Phases open/close on observed events, not prompted milestones:

| Phase | Opens on | Closes when |
|---|---|---|
| `paper_ingest` | Investigate-mode runs, before the SDK call | Paper ingester returns |
| `hypotheses` | `claim_summary` OR first `hypothesis` event (whichever comes first) | First `check` event |
| `checks` | First `check` event | First `verdict`/`fix_applied`/`metric_delta` event |
| `verify` | First `verdict`/`fix_applied`/`metric_delta` | First `dossier_section` |
| `dossier` | First `dossier_section` | First `pr_opened` |
| `pr` | First `pr_opened` | `session_end` |

Phases are monotone — once a phase closes, it never reopens; later events that map to an earlier phase are absorbed by the currently-open phase (or ignored if none is open). On any abnormal termination (cancel, exception), the currently-open phase receives a synthetic `phase_end` before the terminal `session_end`. A run may skip phases (e.g. a Quick Check emits no phase events at all; an investigation that skips the fix jumps straight from `checks` to `dossier`).

### High-level events (Quick Check)

Quick Check is narrower. Most Deep Investigation events do not fire. The server emits only:

| `type` | Emitted when | `data` shape |
|---|---|---|
| `tool_call` / `tool_result` | Same as Deep Investigation | Same |
| `quick_check_verdict` | Agent emits `## Verdict` in Quick-Check mode | `{ "verdict": "confirmed" \| "refuted" \| "unclear", "confidence": 0.88, "evidence": [{"file": "prepare_data.py", "line": 47, "snippet": "imputer.fit(df)"}, ...], "notes": "string" }` |
| `session_end` | Run complete | Same as above |
| `error` | Same | Same |

Quick Check expects exactly one `quick_check_verdict` per run. If the agent cannot converge within `max_turns`, server emits `aborted` then `session_end`.

---

## Pane routing (frontend reducer rules)

These are the rules the frontend reducer (`web/src/state.ts`) applies. Kept here so backend and frontend stay aligned.

| Pane | Feeds from |
|---|---|
| Hypothesis Board | `hypothesis`, `hypothesis_update`, `verdict` |
| Tool Stream | `tool_call`, `tool_result`, `raw_text_delta` (optional debug toggle) |
| Dossier | `claim_summary`, `dossier_section` (rendered in fixed order), `fix_applied`, `metric_delta`, `pr_opened` |
| Quick Check card | `tool_call`, `tool_result`, `quick_check_verdict` |
| Global status bar | `session_start`, `session_end`, `aborted`, `error` |

---

## Ordering guarantees

- `seq` is strictly monotonic within a run. Frontend may use it for out-of-order detection.
- High-level events for a given hypothesis always arrive in order: `hypothesis` → (zero or more `hypothesis_update`) → possibly `verdict`.
- `dossier_section` events are emitted in the order the agent writes them, not in canonical order. Frontend must sort to the canonical order: `claim_tested`, `evidence_gathered`, `root_cause`, `fix_applied`, `remaining_uncertainty`.
- `pr_opened` fires at most once per run and only if `verdict` + `fix_applied` + `metric_delta` have already fired.
- `session_end` is always the final message (followed by the server closing the socket).

---

## Example transcript (abridged Deep Investigation)

```
< {"type":"start", "run_id":"abc", "config":{...}}
> {"type":"session_start", "run_id":"abc", "seq":0, "ts":"...", "data":{"mode":"investigate"}}
> {"type":"claim_summary", "seq":1, "data":{"claim":"RF > LR for civil-war onset."}}
> {"type":"hypothesis", "seq":2, "data":{"id":"h1","rank":1,"name":"Imputation-before-split leakage","confidence":0.6,"reason":"..."}}
> {"type":"hypothesis", "seq":3, "data":{"id":"h2","rank":2,"name":"Class-imbalance handling mismatch","confidence":0.3,"reason":"..."}}
> {"type":"tool_call", "seq":4, "data":{"id":"tu1","name":"Read","input":{"file":"prepare_data.R"}}}
> {"type":"tool_result", "seq":5, "data":{"id":"tu1","name":"Read","output":"...","is_error":false,"duration_ms":80}}
> {"type":"check", "seq":6, "data":{"id":"c1","hypothesis_id":"h1","description":"Inspect imputation order","method":"Read prepare_data.R"}}
> {"type":"finding", "seq":7, "data":{"id":"f1","check_id":"c1","result":"Imputer fit on full df at line 47","supports":["h1"],"refutes":[]}}
> {"type":"hypothesis_update", "seq":8, "data":{"id":"h1","confidence":0.94,"reason_delta":"Confirmed by line 47"}}
> {"type":"verdict", "seq":9, "data":{"hypothesis_id":"h1","confidence":0.94,"summary":"..."}}
> {"type":"tool_call", "seq":10, "data":{"id":"tu2","name":"Edit","input":{...}}}
> {"type":"tool_result", "seq":11, "data":{...}}
> {"type":"fix_applied", "seq":12, "data":{"files_changed":["prepare_data.py"],"diff_summary":"..."}}
> {"type":"tool_call", "seq":13, "data":{"id":"tu3","name":"Bash","input":{"command":"python eval.py"}}}
> {"type":"tool_result", "seq":14, "data":{...}}
> {"type":"metric_delta", "seq":15, "data":{"metric":"AUC","before":0.85,"after":0.72,"baseline":0.74,"context":"RF"}}
> {"type":"dossier_section", "seq":16, "data":{"section":"claim_tested","markdown":"..."}}
... (remaining dossier sections)
> {"type":"pr_opened", "seq":21, "data":{"url":"https://github.com/...","number":42,"title":"..."}}
> {"type":"session_end", "seq":22, "data":{"ok":true,"total_turns":14,"cost_usd":3.21,"duration_ms":187000}}
```

---

## How to verify (end-to-end)

**When backend lands:** run a Deep Investigation on the Muchlinski fixture and log every emitted event to a file. Verify:

1. First event is `session_start` with `seq: 0`.
2. At least 3 `hypothesis` events appear before the first `check`.
3. Every `finding` has a matching `check_id` from a prior `check`.
4. Exactly one `verdict` event fires.
5. `metric_delta.after != metric_delta.before` (the fix actually moved the metric).
6. `pr_opened.url` matches the format `https://github.com/.+/pull/\d+`.
7. Final event is `session_end`.
8. `seq` values are contiguous and monotonic.

**When frontend lands:** connect to a canned event log via a replay mode and verify each pane populates per the routing table above. Add a "replay fixture" toggle in the UI that plays a saved transcript instead of opening a real WS.

---

## REST surface (session management + artifacts)

Beyond the WebSocket, the backend exposes a small REST surface the frontend uses for history, replay, and post-run actions. All return JSON unless noted.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/healthz` | Liveness probe |
| `GET` | `/usage` | Global all-time cost + run count |
| `GET` | `/sessions` | All sessions (pinned first, then newest-activity). Empty sessions omitted. |
| `GET` | `/sessions/{id}` | Session summary with per-run metadata (cost, verdict, model, phase_timings, validity_overall, first_user_text). |
| `POST` | `/sessions/{id}/pin?pinned=true\|false` | Toggle the pinned flag on a session. |
| `POST` | `/sessions/{id}/title?title=...` | Rename a session. Empty string resets to auto-title. |
| `GET` | `/runs/{id}` | Raw `RunMeta` dict for one run |
| `GET` | `/runs/{id}/events.jsonl` | Passthrough of the persisted event log (text/plain). Used for animated replay. |
| `GET` | `/runs/{id}/dossier.md` | Assembled 5-section dossier (text/markdown) |
| `GET` | `/runs/{id}/diff.patch` | Unified git diff of files the agent edited |
| `GET` | `/runs/{id}/paper.md` | The ingested paper as markdown |
| `POST` | `/runs/{id}/validate?force=false` | Run the Validator subagent; returns ValidityReport payload. Cached. |
| `POST` | `/papers/upload` | Multipart PDF upload for Cloudflare-blocked sources. Returns a local path usable as `paper_url`. |
| `POST` | `/repos/attach?input=…` | Resolve a GitHub URL, `owner/repo` slug, or local path into `{local_path, slug, default_branch, source, already_cloned, warning}`. Remote repos are shallow-cloned under `~/.cache/paper-trail/repos/` on first call and reused thereafter. |

Pin/title changes take effect immediately — the next `GET /sessions` reflects them.

---

## Open questions / deferred

- Compression: not needed at MVP scale. Revisit if events get chatty.
- Auth: none at MVP. Single-process, single-session.
- Reconnection: not supported at MVP. Client-side reload = new run.
- Bidirectional mid-stream messages (client cancels mid-run): deferred to post-hackathon.
