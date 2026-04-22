# Frontend — Tool Stream

## Purpose

A live log of every tool call the agent makes — file reads, greps, bash commands, GitHub MCP calls. This pane proves the agent is **actually doing work**, not hallucinating. Collapsible cards so judges can inspect specific calls on demand.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```tsx
// web/src/components/ToolStream.tsx
import type { ToolCallState } from "../state"

interface Props {
  toolCalls: ToolCallState[]       // reducer slice, ordered by arrival
  showRawText?: boolean            // dev toggle; renders raw text deltas interleaved
}

export function ToolStream(props: Props): JSX.Element
```

`ToolCallState`:

```ts
interface ToolCallState {
  id: string
  name: string                  // "Read" | "Bash" | "Grep" | "mcp__github__create_pull_request" | ...
  input: Record<string, unknown>
  output: string | null         // populated when tool_result arrives
  isError: boolean
  durationMs: number | null
  startedAt: string             // ISO
  finishedAt: string | null
}
```

## Events consumed

| Event | Effect |
|---|---|
| `tool_call` | Insert a new card at the top of the list with `output: null` (in-flight state). |
| `tool_result` | Find the matching card by `id`, fill in `output`, `isError`, `durationMs`, `finishedAt`. |
| `raw_text_delta` | Only rendered if `showRawText` is true. Dimmed monospace text between cards. |

## Visual design

### Card (per tool call)

```
┌─ ▾ Read · prepare_data.py ─────────────── 80ms · OK ──┐
│                                                        │
│  input: { file_path: "prepare_data.py" }               │
│                                                        │
│  output (collapsed)                                    │
│                                                        │
└────────────────────────────────────────────────────────┘
```

Expanded:

```
┌─ ▴ Read · prepare_data.py ─────────────── 80ms · OK ──┐
│                                                        │
│  input: { file_path: "prepare_data.py" }               │
│                                                        │
│  output:                                               │
│  ┌──────────────────────────────────────────────────┐  │
│  │  1  import pandas as pd                          │  │
│  │  2  from sklearn.impute import IterativeImputer  │  │
│  │  ...                                             │  │
│  │ 47  imputer.fit(df)                              │  │
│  │ 48  df = imputer.transform(df)                   │  │
│  │ 49  train, test = train_test_split(df, ...)     │  │
│  └──────────────────────────────────────────────────┘  │
│                                                        │
└────────────────────────────────────────────────────────┘
```

- Card header: chevron + tool name + key input arg (e.g., filename) + duration + status badge.
- Collapsed by default; click to expand. Keyboard `Enter` on focused card toggles.
- In-flight cards show a subtle pulsing loader where the duration would be.
- Error cards (`isError: true`) have a red left border and a red status badge.

### List behavior

- Newest tool call at the **top** (so the user sees activity without scrolling).
- Virtualized if >50 items (Tool Stream can get long during 30-turn runs).
- Autoscroll to newest only if the user hasn't manually scrolled.

### Tool-specific renderers

Some tools benefit from bespoke rendering:

| Tool | Rendering |
|---|---|
| `Read` | Show line numbers + syntax highlighting (monokai-ish theme via `shiki` or `highlight.js`) |
| `Grep` | Show matched lines only; highlight match |
| `Bash` | Show command + stdout + exit code; ANSI color codes rendered |
| `Edit` | Show unified diff (`+`/`-` lines) |
| `mcp__github__create_pull_request` | Show the rendered PR body as markdown + the returned URL as a clickable button |

Other tools fall back to a generic JSON renderer.

## Implementation notes

### Syntax highlighting

Use `shiki` (server-side prebundled themes) or `highlight.js` (smaller bundle). shiki produces nicer output; hljs is faster. Pick by Day 3 based on bundle size measurement.

### ANSI handling

Bash output can contain ANSI escape codes. Use `ansi-to-html` or similar to render colors.

### Performance

- Memoize card components by `id`.
- Only expand 1-2 cards at a time automatically (the latest + any erroring).
- Large outputs (>10k chars) truncated with "show more" — don't render 200k of training logs.

### Debug toggle

`showRawText` is a dev-only toggle accessible via a gear icon. When enabled, `raw_text_delta` events render interleaved with tool calls as dimmed gray monospace. Off by default.

### Accessibility

- Each card is a `<details>` / `<summary>` pair for native expand/collapse behavior.
- Status announced via `aria-live="polite"` region (but throttled — don't scream every tool call).

## How to verify (end-to-end)

### Setup

Running backend + frontend with Muchlinski Deep Investigation.

### Checks

1. Within 10s of run start, Tool Stream has ≥1 in-flight card (usually `Read prepare_data.py`).
2. Card transitions from "in-flight" to "finished" state within a few seconds; duration shown.
3. Reading a file renders as syntax-highlighted line-numbered code when expanded.
4. When the agent runs `Bash: python eval.py`, output appears with stdout (including any ANSI colors from sklearn warnings) intact.
5. When the agent opens a PR, the `mcp__github__create_pull_request` card shows the PR body preview and a clickable URL.
6. Tool Stream can handle 30+ tool calls without visible jank.
7. Autoscroll: leaving the pane alone → scroll pins to top. Manually scrolling down → stays put even as new cards arrive.

### Expected failure modes

- **Tool cards appear after a long delay.** SDK might be batching deltas. Verify `include_partial_messages=true` server-side.
- **Output looks like mojibake.** Encoding issue; ensure server sends `output` as UTF-8 string, not bytes.
- **Long outputs break layout.** Add `overflow-x: auto` on the code block container; truncate anything >10k chars.
- **Diff tool output unreadable.** Wrap with a proper diff renderer (`react-diff-viewer-continued`).

## Open questions / deferred

- "Filter by tool name" dropdown: nice-to-have.
- Click a tool call to jump to the related Hypothesis card (already discussed in [hypothesis_board.md](hypothesis_board.md)): `DEFERRED`.
- Export Tool Stream as a newline-delimited JSON log: small and useful, maybe Day 5.
