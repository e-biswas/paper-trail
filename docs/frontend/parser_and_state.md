# Frontend — Parser + State Reducer

## Purpose

The non-visual core of the frontend. `parser.ts` validates incoming envelope events and narrows their TypeScript types. `state.ts` is a `useReducer` that routes events into per-pane slices. Together they implement the pane-routing table from [../integration.md](../integration.md#pane-routing-frontend-reducer-rules).

## Status

`TODO` · last updated 2026-04-21

## Public interface

### `src/types.ts`

Mirrors the envelope schema from [../integration.md](../integration.md). Exports:

```ts
export type EventType =
  | "session_start" | "session_end" | "error" | "aborted"
  | "raw_text_delta" | "tool_call" | "tool_result"
  | "claim_summary"
  | "hypothesis" | "hypothesis_update"
  | "check" | "finding"
  | "verdict" | "fix_applied" | "metric_delta" | "dossier_section" | "pr_opened"
  | "quick_check_verdict"

export interface Envelope<T extends EventType = EventType, D = unknown> {
  type: T
  run_id: string
  ts: string
  seq: number
  data: D
}

// Per-type payload types (e.g.):
export interface HypothesisPayload { id: string; rank: number; name: string; confidence: number; reason: string }
// ... one per event type; keep in lockstep with integration.md
```

### `src/parser.ts`

```ts
import type { Envelope, EventType } from "./types"

/** Validates + narrows; throws on malformed envelope. */
export function parseEnvelope(raw: unknown): Envelope

/** Type-narrowing predicate for discriminated union dispatch. */
export function isEventOfType<T extends EventType>(e: Envelope, t: T): e is Envelope<T>
```

### `src/state.ts`

```ts
export interface AppState {
  mode: "investigate" | "check" | null
  status: "idle" | "connecting" | "running" | "success" | "error" | "aborted"
  claimSummary: string | null
  hypotheses: Record<string, HypothesisState>      // keyed by id
  hypothesisOrder: string[]                        // maintains insertion / rank order
  verdict: VerdictState | null
  toolCalls: Record<string, ToolCallState>         // keyed by id
  toolCallOrder: string[]
  dossier: DossierState
  quickChecks: Record<string, QuickCheckState>    // keyed by run_id
  quickCheckOrder: string[]
  cost: { total_usd: number; turns: number }
  errors: { code: string; message: string; ts: string }[]
}

export type Action =
  | { kind: "reset" }
  | { kind: "status"; value: AppState["status"] }
  | { kind: "envelope"; envelope: Envelope }

export const initialState: AppState = { ... }
export function reducer(state: AppState, action: Action): AppState
```

Context exposed via:

```tsx
// src/state.ts
export const AppContext = createContext<{state: AppState; dispatch: Dispatch<Action>}>(...)
export function AppProvider({ children }: { children: ReactNode }): JSX.Element
```

Components consume via `useContext(AppContext)`.

## Events consumed (dispatcher table)

```
envelope.type           → reducer slice updated
─────────────────────────────────────────────────────
session_start           → mode, status="running", clear errors
session_end             → status based on data.ok, cost += data.cost_usd
error                   → status="error", push onto errors[]
aborted                 → status="aborted", set dossier.aborted
claim_summary           → claimSummary
hypothesis              → upsert hypotheses[id], append to hypothesisOrder
hypothesis_update       → update hypotheses[id].confidence + confidenceHistory
check                   → hypotheses[hypothesis_id].status = "checking"
finding                 → hypotheses[h].status = "confirmed"|"refuted" per supports/refutes
verdict                 → verdict; hypotheses[hypothesis_id].status = "confirmed"
fix_applied             → dossier.fixApplied
metric_delta            → dossier.metricDelta
dossier_section         → dossier.sections[section] = markdown
pr_opened               → dossier.pr
quick_check_verdict     → quickChecks[run_id].verdict (routed by run_id)
tool_call (investigate) → toolCalls[id] + toolCallOrder
tool_call (check)       → quickChecks[run_id].toolCalls (routed by run_id)
tool_result             → as above, updates existing toolCall
raw_text_delta          → dropped unless debug toggle is on (then appended to a ring buffer)
```

## Implementation notes

### Routing by `run_id`

Envelopes from `/ws/check` contain a `run_id` that maps to a specific Quick Check card. Envelopes from `/ws/investigate` use the single in-flight Deep Investigation `run_id`. Reducer uses the current mode + `run_id` to decide whether a `tool_call` goes to the main Tool Stream or a Quick Check card.

```ts
function routeToolCall(state: AppState, env: Envelope<"tool_call">): AppState {
  if (state.mode === "investigate" && env.run_id === state.currentDeepRunId) {
    return { ...state, toolCalls: upsert(state.toolCalls, env.data), toolCallOrder: [env.data.id, ...state.toolCallOrder] }
  }
  if (env.run_id in state.quickChecks) {
    const qc = state.quickChecks[env.run_id]
    return { ...state, quickChecks: { ...state.quickChecks, [env.run_id]: { ...qc, toolCalls: [env.data, ...qc.toolCalls] } } }
  }
  return state
}
```

### Immutability + referential equality

- Reducer always returns a new top-level object.
- Slice-level changes return new dictionaries only for the slices that changed (let React bail out of unchanged panes).
- No mutation. Strict mode enabled in Vite dev to catch accidental mutation.

### Ordering guarantees

- `seq` is monotonic per run. Reducer verifies it and drops out-of-order envelopes with a console warning (shouldn't happen; signals a bug).
- `hypothesisOrder` and `toolCallOrder` preserve insertion order; on `hypothesis_update` the order does NOT change (stable render).

### Validation strictness

`parseEnvelope` is strict on the envelope shell (`type`, `run_id`, `ts`, `seq`, `data`) but **lenient on unknown `type` values** — frontend must ignore unknown types gracefully per [../integration.md](../integration.md#envelope-format).

### Error handling in the reducer

- Malformed envelope → `errors[]` entry, no state corruption.
- Event for unknown `run_id` → dropped with console warning.

## How to verify (end-to-end)

### Unit-ish tests via scripted manual replay

1. Save a real envelope stream to `web/src/fixtures/replay.json` (from running the Muchlinski demo with stdout capture in the backend smoke test).
2. Create a dev-only "Replay" button in the App shell that loads the fixture and dispatches each envelope through the reducer with a 50ms delay.
3. Verify that final state matches what a real run produces:
   - `claimSummary` set
   - `hypothesisOrder.length >= 3`
   - `verdict` set
   - `dossier.sections` has all 5 canonical keys
   - `dossier.pr.url` is set
   - `toolCalls` has >10 entries
   - `status === "success"`

### Integration (full demo)

Part of the full frontend verification in [README.md](README.md#how-to-verify-end-to-end--whole-frontend).

### Expected failure modes

- **State leaks between runs.** Dispatch `{kind: "reset"}` on every new run start. Verify.
- **Hypothesis cards duplicate.** Upsert by id, not push.
- **Quick Check events land in the main Tool Stream.** Fix `routeToolCall` run_id routing.
- **Reducer throws on unknown type.** Must log + return state unchanged, not throw.

## Open questions / deferred

- Persist reducer state across reloads via localStorage: `DEFERRED`.
- Undo/redo past runs: out of scope.
- Move to Redux Toolkit / Zustand if the reducer grows unwieldy: probably not needed; reconsider if we exceed ~300 LOC.
