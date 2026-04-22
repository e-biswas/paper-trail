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

## Open questions / deferred

- Run history: `DEFERRED`.
- Keyboard navigation of Hypothesis Board cards: nice-to-have, not in MVP.
- Persist last-used paper URL in localStorage: small win, maybe Day 5 if time.
