# Frontend — Quick Check Sidebar

## Purpose

Chat-style sidebar for one-off verification questions. Each question spawns a bounded agent run; each run produces a verdict card with code citations. This is the "verification intern" surface — daily-use, not one-shot.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```tsx
// web/src/components/QuickCheck.tsx
import type { QuickCheckState } from "../state"

interface Props {
  checks: QuickCheckState[]           // ordered by arrival, newest at top
  repoPath: string                    // from App shell; piped into each run's start frame
  onSubmit: (question: string) => void  // opens a fresh /ws/check socket
}

export function QuickCheck(props: Props): JSX.Element
```

`QuickCheckState`:

```ts
interface QuickCheckState {
  id: string                      // run_id
  question: string
  status: "running" | "complete" | "aborted" | "error"
  toolCalls: ToolCallState[]      // scoped to this check only
  verdict: {
    verdict: "confirmed" | "refuted" | "unclear"
    confidence: number
    evidence: { file: string; line: number; snippet: string }[]
    notes: string
  } | null
  costUsd: number | null
  durationMs: number | null
}
```

## Events consumed

Each Quick Check owns a separate WebSocket (opened on submit). While open, events are scoped to that check's card:

| Event | Effect |
|---|---|
| `tool_call` / `tool_result` | Append to this check's `toolCalls` (shown in a small inline log) |
| `quick_check_verdict` | Set `verdict` |
| `session_end` | Set `status: "complete"`, record `costUsd` and `durationMs` |
| `aborted` | Set `status: "aborted"` |
| `error` | Set `status: "error"` |

## Visual design

### Sidebar layout

```
┌ Quick Check ──────────────────────────────┐
│                                            │
│  ┌────────────────────────────────────┐    │
│  │ Ask a verification question...   ⏎ │    │
│  └────────────────────────────────────┘    │
│                                            │
│  Try:                                      │
│  [ Is imputation fit on train only? ]      │
│  [ Are patient IDs leaking? ]              │
│  [ Any duplicate rows? ]                   │
│                                            │
│  ─────────────────────────────────────     │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ ⚠ REFUTED  · 0.94  · 12s · $0.08     │  │
│  │                                      │  │
│  │ "Is imputation fit on train only?"   │  │
│  │                                      │  │
│  │ Imputer.fit() runs on full df at     │  │
│  │ prepare_data.py:47 — before the      │  │
│  │ train/test split at line 63.         │  │
│  │                                      │  │
│  │ Evidence:                            │  │
│  │  · prepare_data.py:47                │  │
│  │    imputer.fit(df)                   │  │
│  │                                      │  │
│  │ ▸ 2 tool calls                       │  │
│  └──────────────────────────────────────┘  │
│                                            │
│  ┌──────────────────────────────────────┐  │
│  │ ✓ CONFIRMED · 0.88 · 8s · $0.04      │  │
│  │ "Are patient IDs leaking?"           │  │
│  │ ...                                  │  │
│  └──────────────────────────────────────┘  │
│                                            │
└────────────────────────────────────────────┘
```

### Card states

- **Running:** skeleton with a pulsing header "thinking…", tool-call count incrementing live.
- **Complete:** verdict header with color + icon + confidence + duration + cost.
- **Aborted:** gray header, reason shown.
- **Error:** red header, error message.

### Verdict header

| Verdict | Color | Icon |
|---|---|---|
| `confirmed` | emerald | ✓ |
| `refuted` | rose | ⚠ |
| `unclear` | amber | ? |

### Canned suggestion chips

Pre-seeded from `web/src/lib/quick_check_prompts.ts`:

```ts
export const CANNED_PROMPTS = [
  "Is imputation fit on train only, or on all data?",
  "Does the train/test split respect patient/group boundaries?",
  "Are there exact-duplicate rows between train and test?",
]
```

Clicking a chip populates the textarea but does NOT auto-submit — user hits Enter.

### Input box

- Single textarea (shadcn `<Textarea>`), 3 rows default, expands up to 8.
- Submit via Enter (Shift+Enter for newline).
- `⌘K` / `Ctrl+K` focuses this field (from [app_shell.md](app_shell.md)).
- Disabled while `repoPath` is not set.

### Concurrency

- Users can have multiple Quick Checks running simultaneously. The sidebar shows them all, newest at top.
- Cost and duration badges accumulate; the overall cost counter in the StatusBar includes Quick Checks too.

### Empty state

```
    Ask anything about the repo. A full
    investigation takes minutes — a quick
    check takes seconds.
```

## Implementation notes

### WebSocket per check

Each submit opens `ws://localhost:8080/ws/check` with a fresh `run_id`. Close on `session_end` / error / aborted. No shared socket across checks — simpler state, independent failures.

### Tool-call log collapse

Each Quick Check card has a collapsible tool-call log. Collapsed by default (show "▸ N tool calls"). Expanding reuses the [ToolStream](tool_stream.md) card visual for consistency.

### Verdict text formatting

- Notes render as markdown (single paragraph usually).
- Evidence list: each entry renders `file:line` as a monospace badge + the snippet in a small code block.
- If >3 evidence entries, show first 2 + "show all (N)" toggle.

### Accessibility

- Each verdict card is a `<section>` with `aria-live="polite"` while running.
- Sidebar keyboard-navigable: Tab cycles through cards and the input.
- Color + icon + text for verdict (redundant, not color-only).

## How to verify (end-to-end)

### Setup

Backend running, Muchlinski fixture staged.

### Checks

1. Sidebar visible on the right. Input focused via `⌘K`.
2. Click the first canned chip. Textarea populates. Press Enter.
3. Card appears at top with "running" state. Tool-call count increments live.
4. Within 30s, card transitions to "complete" with `verdict: refuted`, confidence ≥ 0.8, ≥1 evidence entry citing `prepare_data.py:47`.
5. Click the "▸ N tool calls" to expand; see individual tool calls.
6. Submit a free-text question ("does this repo use GroupShuffleSplit?") — new card appears alongside, doesn't disturb the first.
7. Kill backend mid-run. Card transitions to "error" state with a useful message.

### Expected failure modes

- **Verdict arrives but no evidence.** Prompt may have allowed loose output; strengthen `quick_check.md` schema.
- **Cards move around when a new one arrives.** Keep insertion order stable; animate new card entering.
- **Tool-call count never updates.** Reducer must bucket events by `run_id`.
- **Multiple Quick Checks running → events mingled across cards.** Check reducer's per-run slicing.

## Known gaps / corner cases

- **MAJOR — evidence `file:line` citations render as plain monospace
  text, not clickable.** Judges can't jump to the cited line from
  the verdict card. Fix sketch: render each `file:line` as a
  `<button>` that dispatches a "jump" action; Tool Stream surfaces
  a matching `Read` card if present, otherwise no-op with a toast.
- **MAJOR — verdict badges signal by color only.** `confirmed` /
  `refuted` / `unclear` use emerald / rose / amber with no redundant
  text or icon, violating colorblind-safe guidance. Spec already
  lists the icon table; enforce it in the badge component.
- **MINOR — turn-cap / time-budget not shown in the sidebar.**
  The card displays elapsed time and cost after completion, but a
  running Quick Check gives no indication of how close it is to the
  8-turn cap or the ~60 s budget. Add a small `3/8 turns · 12 s` line
  while running.

## Open questions / deferred

- Persist Quick Check history in localStorage across reloads: `DEFERRED`, small cost.
- "Ask this about the backup fixture too" one-click repeat: `DEFERRED`.
- Streaming partial evidence before final verdict: nice, but Quick Check is fast enough not to need it.
