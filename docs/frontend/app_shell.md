# Frontend — App Shell

## Purpose

The top-level layout, input form, mode toggle, WebSocket client, and global status bar. This is the frame everything else renders into.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```tsx
// web/src/App.tsx
export default function App(): JSX.Element
```

No props. Internally holds:

- `runId: string | null`
- `mode: "investigate" | "check"`
- `status: "idle" | "connecting" | "running" | "success" | "error" | "aborted"`
- Reducer state from `src/state.ts`

Uses:

- `useWebSocket` hook from `src/ws.ts`
- `useReducer` with reducer from `src/state.ts`

## Layout

Grid-based, CSS grid via Tailwind. Target 1440×900.

```
┌─────────────────────────────────────────────────────────────────────┐
│ StatusBar: Paper Trail · mode · status · cost · turns │
├─────────────────────────────┬───────────────────────────────────────┤
│                             │                                       │
│   Input form                │   Quick Check sidebar                 │
│   (paper URL, repo path,    │   (chat-style card list)              │
│    run button)              │                                       │
│                             │                                       │
├─────────────────────────────┤                                       │
│                             │                                       │
│   Hypothesis Board          │                                       │
│   (ranked cards)            │                                       │
│                             │                                       │
├─────────────────────────────┤                                       │
│                             │                                       │
│   Tool Stream               │                                       │
│   (scrolling log)           │                                       │
│                             │                                       │
├─────────────────────────────┤                                       │
│                             │                                       │
│   Dossier                   │                                       │
│   (5 sections + PR link)    │                                       │
│                             │                                       │
└─────────────────────────────┴───────────────────────────────────────┘
```

Grid: two columns. Left column is 2fr (Hypothesis Board + Tool Stream + Dossier stacked). Right column is 1fr (Quick Check sidebar). Status bar spans the full width at the top. Input form is above the Hypothesis Board in the left column, collapsed to a thin bar after the first run starts.

## Implementation notes

### Input form

- Two text inputs: **Paper URL** and **Repo path** (absolute local path to a pre-staged fixture).
- Two shadcn `<Select>` chips for "Primary demo" / "Backup demo" that prefill the inputs.
- Single **Run Deep Investigation** button.
- After a run starts, the form collapses to a one-line summary with a **Run again** action.

### Mode switching

- Quick Check is always available in the right sidebar; it doesn't disable Deep Investigation.
- Deep Investigation and Quick Check open separate WebSockets so they can run concurrently.

### WebSocket client (`src/ws.ts`)

```ts
type UseWS = { connect: (url: string, startFrame: unknown) => void; status: WsStatus; lastEvent: Envelope | null }
export function useWebSocket(onEvent: (e: Envelope) => void): UseWS
```

Responsibilities:

- Open/close the socket.
- Send the `start` frame once open.
- Parse every frame as JSON, validate via `src/types.ts` guards, call `onEvent`.
- Map socket state → `status`: `idle | connecting | running | success | error | aborted`.

### Global StatusBar

A thin bar at the top showing:

- App name
- Current mode (`investigate` / `check`)
- Status dot (colored by state)
- Live cost counter (sum of `cost_usd` from `session_end` events)
- Turn counter (current run)
- Toggle: dark/light (default dark)

### Dev/demo prefills

On first load, the input form is prefilled with the primary demo's paper URL and repo path (`/tmp/muchlinski-demo`). Rationale: the demo must start on first click, no typing.

### Error presentation

- `error` envelopes show a toast (shadcn `Sonner`) with the error message.
- `aborted` envelopes show an inline banner above the Dossier with the abort reason.
- Neither crashes the UI. Run state transitions to a terminal state.

### Keyboard shortcuts

- `Enter` in the input form runs Deep Investigation.
- `⌘K` / `Ctrl+K` focuses the Quick Check input.
- `Esc` closes any open modal.

## How to verify (end-to-end)

### Setup

```bash
npm --prefix web install
npm --prefix web run dev
```

### Checks

1. Open `http://localhost:5173`. Dashboard shell renders, status dot is gray ("idle"), primary demo prefilled.
2. Inputs editable. Clicking **Backup demo** prefills different values.
3. Click **Run Deep Investigation** with the dev server not connected → status goes `connecting` → `error`, toast shows a useful message. No crash.
4. Boot backend, click **Run Deep Investigation** → status: `connecting` → `running`. Hypothesis Board begins populating.
5. Toggle Quick Check sidebar + run a canned check → sidebar card appears concurrent with Deep Investigation. Both independent.
6. Dark/light toggle works; all shadcn components pick up the theme.
7. `⌘K` focuses Quick Check input; typing a question + Enter sends it.

### Expected failure modes

- **Inputs look cramped.** Widen input column to min-width 520px.
- **Sidebar obscures main content on smaller screens.** Collapse sidebar to a drawer below 1200px width.
- **Status bar doesn't update.** Reducer probably not dispatching; check `state.ts`.

## Abort button + live cost pill (DONE — TASKS D5.X-abort-frontend)

The chat-reframe architecture moved the live status controls off a
separate status bar and into each assistant message's header row (next
to the mode / model / status badge). The behaviour matches the original
spec:

- **Abort button.** `AssistantMessage.tsx` renders a compact `◼ Abort`
  pill whenever `status === "running"` and the parent supplies an
  `onStop` callback. Clicking calls `chatStore.stopRun()`, which sends
  `{"type":"stop"}` over the live WebSocket. Backend cancels the agent
  task and emits a terminal `session_end` with `stop_reason:
  "user_abort"`; the existing `ABORT_REASON_LABEL` map supplies the
  human-readable copy. Uses the `status.refuted` rose token.
- **Cost pill.** Small chip rendered next to the status badge showing
  `$x.xxxx` during the run. Value = `max(streamedCost, cost_usd)` where
  `streamedCost` is updated by the `cost_update` reducer (rate-limited
  on the backend to ≥750 ms). Pulses via a framer-motion key-swap on
  each new total. After `session_end`, converges to
  `session_end.cost_usd`.

## Known gaps / corner cases

- **BLOCKER — WS URL hardcoded to `location.host`, no
  `VITE_BACKEND_URL` fallback.** [web/src/state/chatStore.ts:96](../../web/src/state/chatStore.ts#L96)
  prevents pointing the dev frontend at a remote backend.
- **BLOCKER — no WS reconnect on drop.**
  [web/src/state/chatStore.ts:179-183](../../web/src/state/chatStore.ts#L179-L183)
  surfaces a dropped connection as a generic "WebSocket error" with
  no retry. At minimum, show "Connection lost" with a Retry button;
  backoff is explicitly deferred (see plan) but the user-visible
  state must not regress to silent failure.
- **MAJOR — fixture paths hardcoded.** Primary fixture path +
  paper URL baked into [App.tsx:9-12](../../web/src/App.tsx#L9-L12)
  and [InputRow.tsx:143-161](../../web/src/components/chat/InputRow.tsx#L143-L161);
  no way to switch to backup without editing code. Flagged here
  because demo act 4 (ISIC generalization beat) depends on the
  switcher.
- **MINOR — no distinction between "ran to completion" and
  "connection dropped".** Both paths close the socket and set a
  terminal-looking status. The cost pill freeze + a small "disconnected"
  annotation should differentiate.
- **MINOR — dark/light toggle mentioned in status bar spec but not
  implemented.** No urgency; keep deferred.

## Open questions / deferred

- Run history: `DEFERRED`.
- Keyboard navigation of Hypothesis Board cards: nice-to-have, not in MVP.
- Persist last-used paper URL in localStorage: small win, maybe Day 5 if time.
