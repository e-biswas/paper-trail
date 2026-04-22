# Frontend — Hypothesis Board

## Purpose

The **signature UI element** of the demo. Renders the agent's ranked hypotheses as cards with live confidence bars. This is the pane that sells the "watch it think" feeling — every `hypothesis`, `hypothesis_update`, and `verdict` event animates here.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```tsx
// web/src/components/HypothesisBoard.tsx
import type { HypothesisState } from "../state"

interface Props {
  hypotheses: HypothesisState[]       // from reducer slice
  verdict: { hypothesis_id: string; confidence: number; summary: string } | null
  status: "idle" | "running" | "success" | "aborted" | "error"
}

export function HypothesisBoard(props: Props): JSX.Element
```

`HypothesisState` (also in `src/state.ts`):

```ts
interface HypothesisState {
  id: string
  rank: number
  name: string
  confidence: number        // 0..1
  confidenceHistory: {ts: string; value: number}[]  // for sparkline
  reason: string
  reasonDelta?: string      // most recent update reason
  status: "pending" | "checking" | "confirmed" | "refuted"
}
```

## Events consumed

(From [../integration.md](../integration.md))

| Event | Effect |
|---|---|
| `hypothesis` | Append new card. Animate fade-in from top of list. |
| `hypothesis_update` | Update card's confidence (animate bar fill) and append to `confidenceHistory`. Flash `reasonDelta` for ~3s. |
| `check` | Mark referenced hypothesis with `status: "checking"` — add a pulsing ring around the card. |
| `finding` | For hypotheses in `supports[]`, flash green; for `refutes[]`, flash red. No confidence change (that's `hypothesis_update`). |
| `verdict` | Highlight the winning card (gold border + 🏆 badge). Collapse or dim other cards. |

## Visual design

### Card (per hypothesis)

```
┌─ Rank #1 ──────────────────────────────────────────────┐
│                                                        │
│  Imputation-before-split leakage                 🏆    │
│                                                        │
│  ██████████████░░░░░░  0.72 → 0.95 ↑                   │
│                                                        │
│  Amelia fits on the full panel before train/test       │
│  split, leaking test info into training.               │
│                                                        │
│  ✓ Confirmed by Finding f1 at prepare_data.R:47        │
│                                                        │
└────────────────────────────────────────────────────────┘
```

- Card uses shadcn `<Card>` with a left-border indicator colored by status: gray (pending) → blue (checking) → green (confirmed) → red (refuted) → gold (verdict).
- Confidence bar: a Tailwind-styled progress bar. Width animates via CSS transition. Show previous → current value on updates (brief "0.72 → 0.95" label that fades after 3s).
- Reason text in smaller sans-serif. Reason deltas in italic, dimmed.
- Status line at the bottom references the finding id that flipped it.

### Layout

- Cards stacked vertically, sorted by `rank` ascending.
- Max 5 cards visible; more scroll within the pane.
- Empty state: a subtle "Waiting for hypotheses…" skeleton with 3 dimmed rectangles.

### Animations

- Card enter: `opacity 0 → 1`, `translateY(-8px) → 0` over 200ms.
- Confidence bar: width transition 400ms ease-out.
- Verdict highlight: pulsing gold glow for 2s, then persistent gold border.
- All animations respect `prefers-reduced-motion`.

### Color palette

Uses the design tokens from [styling.md](styling.md). Status colors:

- Pending: `slate-500`
- Checking: `blue-500` (pulse)
- Confirmed: `emerald-500`
- Refuted: `rose-500`
- Verdict: `amber-400` (gold)

## Implementation notes

### Sorting stability

When `rank` ties, preserve insertion order (don't reshuffle cards mid-run — it's visually jarring).

### Confidence history sparkline (stretch)

On hover, show a tiny 60×20px sparkline of `confidenceHistory`. Useful for showing "confidence grew with evidence." If Day 4 is tight, skip this.

### Verdict collapse behavior

When a `verdict` event fires, the winning card enlarges slightly; other cards shrink to ~80% scale and dim to 60% opacity. This directs the judge's eye without removing context.

### Accessibility

- Each card is a `<section>` with `aria-label="Hypothesis {rank}: {name}"`.
- Confidence bar has `role="progressbar"` with `aria-valuenow`.
- Status color changes paired with icon (✓ / ✗ / 🏆) so colorblind users aren't reliant on hue.

## How to verify (end-to-end)

### Standalone (no backend)

Use the replay fixture (stretch) or mock a reducer state via a Storybook story (also stretch). If neither, verify via full backend.

### Full path

1. Start backend + frontend, click **Run Deep Investigation** on Muchlinski.
2. Within 15s, first card fades in. Name is a real failure-class name (not "Hypothesis 1").
3. At least 3 cards appear within 30s.
4. As checks run, cards flash blue pulse; as findings arrive, cards flash green or red.
5. Confidence bars animate smoothly (no jumpy resets).
6. Verdict event → one card goes gold, others dim.
7. After `session_end`, final state is stable (no flickering).

### Expected failure modes

- **Cards re-render from scratch on every update** (flicker). Memoize by `id` in the list. Use stable keys.
- **Confidence bar snaps, doesn't animate.** Missing Tailwind transition class; verify `transition-[width]` or equivalent.
- **Two hypotheses with the same id** (duplicate on `hypothesis` event). Reducer must upsert by id, not append blindly.
- **Verdict card doesn't stand out enough.** Increase gold glow intensity or enlarge scale.

## Open questions / deferred

- Click a hypothesis card to filter Tool Stream to only its checks: high UX value, Day 5 if time.
- Drag to reorder: out of scope.
- Export hypothesis board as PNG for the PR body: `DEFERRED`.
