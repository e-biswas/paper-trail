# Frontend — Dossier

## Purpose

The final evidence artifact the demo converges on. Renders five fixed sections of the agent's scientific audit report in canonical order, plus the before/after metric delta and the GitHub PR link. This is what the judge clicks on at the end of the demo.

## Status

`TODO` · last updated 2026-04-21

## Public interface

```tsx
// web/src/components/Dossier.tsx
import type { DossierState } from "../state"

interface Props {
  dossier: DossierState
  status: "pending" | "in_progress" | "complete" | "aborted"
}

export function Dossier(props: Props): JSX.Element
```

`DossierState`:

```ts
interface DossierState {
  claimSummary: string | null                              // from claim_summary event
  sections: Partial<Record<DossierSection, string>>        // markdown per section
  fixApplied: { files: string[]; summary: string } | null
  metricDelta: { metric: string; before: number; after: number; baseline?: number; context: string } | null
  pr: { url: string; number: number; title: string } | null
  aborted: { reason: string; detail: string } | null
}

type DossierSection =
  | "claim_tested"
  | "evidence_gathered"
  | "root_cause"
  | "fix_applied"
  | "remaining_uncertainty"
```

## Events consumed

| Event | Effect |
|---|---|
| `claim_summary` | Sets `claimSummary`. |
| `fix_applied` | Sets `fixApplied`. |
| `metric_delta` | Sets `metricDelta`. Animate numbers counting up/down. |
| `dossier_section` | Upserts `sections[section]` with the provided markdown. Render immediately. |
| `pr_opened` | Sets `pr`. Pops the PR link to the top of the pane with a subtle attention animation. |
| `aborted` | Sets `aborted`. Replaces the PR link area with an abort banner. |

## Visual design

### Layout

```
┌────────────────────────────────────────────────────────────────┐
│   📄 Reproducibility Dossier                                   │
│                                                                │
│   Claim:                                                       │
│   > RF beats LR for civil-war onset prediction.                │
│                                                                │
│   Metric delta:          [AUC]  0.85 → 0.72  (baseline 0.74)   │
│   Files changed:         prepare_data.py                       │
│                                                                │
│   ┌──────────────────────────────────────────────────────────┐ │
│   │ 📎 PR #42 · Fix imputation-before-split leakage          │ │
│   │    https://github.com/bot/muchlinski-demo/pull/42    →   │ │
│   └──────────────────────────────────────────────────────────┘ │
│                                                                │
│   ─── Evidence gathered ──────────────────────────────────     │
│                                                                │
│   <markdown rendered here>                                     │
│                                                                │
│   ─── Root cause ─────────────────────────────────────────     │
│                                                                │
│   <markdown>                                                   │
│                                                                │
│   ─── Fix applied ────────────────────────────────────────     │
│                                                                │
│   <markdown, includes a diff block>                            │
│                                                                │
│   ─── Remaining uncertainty ──────────────────────────────     │
│                                                                │
│   <markdown>                                                   │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

- Header shows the claim summary as a pull quote.
- Metric delta is prominent — large numbers, delta color-coded (red if metric dropped in a good way — i.e., honest reveal of inflated claim; green if the fix improved metric).
- PR link is the most visually prominent element after the metric delta — large button/card with icon + URL.
- The five sections in canonical order, with clear section dividers.
- Each section renders as markdown (use `react-markdown` + `remark-gfm`).

### Metric delta styling

```
AUC  0.85 → 0.72     (baseline: 0.74)
       ─────────────
       Δ  -0.13 (−15%)
```

- `before` and `after` numbers in a large monospace font.
- Color logic: red if the metric dropped (honest reveal); irrelevant to "good/bad." Paired with neutral label ("Honest result: the paper's claim doesn't hold").
- Baseline (if provided) shown as reference line.

### Progressive rendering

- Sections appear one at a time as they arrive (not a big reveal at the end).
- A faint "writing…" indicator under the last-arrived section until the next one arrives.
- On `session_end`, all indicators cleared; pane is stable.

### Empty state

Before any dossier events arrive:

```
   📄 Reproducibility Dossier
   Waiting for verdict. The dossier will build up here as the
   agent gathers evidence and proposes a fix.
```

### Aborted state

```
   ⚠ Investigation aborted
   Reason: turn cap reached without verdict
   Detail: hypotheses h1 (0.78) and h2 (0.65) were not disambiguated
```

## Implementation notes

### Markdown renderer

Use `react-markdown` with `remark-gfm` (tables, strikethrough, task lists). Syntax highlighting inside code fences via `rehype-shiki` or `rehype-highlight`.

### PR button

Is an `<a target="_blank" rel="noopener">` styled as a shadcn `<Button>` with external-link icon. Subtle shimmer on first render to draw the eye.

### Animations

- Metric numbers count up/down via CSS transition or `react-spring` (one number, very lightweight).
- Section dividers fade in with the section.
- PR card pulses gently on first render (2 pulses, then stops).

### Accessibility

- Each section has an `id` derived from its section key so deep-links work (`#dossier-root-cause`).
- PR link has an `aria-describedby` pointing to the metric delta, so screen readers hear context.

## How to verify (end-to-end)

### Full path

1. Run Deep Investigation on Muchlinski.
2. Within the first 30s, claim summary appears in the Dossier header.
3. As the run progresses, sections materialize one at a time.
4. Metric delta appears with animated numbers (0.85 → 0.72). Delta shown (−15%).
5. PR link appears at the top. Clicking opens the real PR in a new tab.
6. All five canonical sections are populated and in order.
7. No flicker or reordering on subsequent updates.
8. On an `aborted` run, abort banner appears in place of the PR link; sections that did fire are still shown.

### Expected failure modes

- **Sections appear out of order.** Reducer must reorder to canonical sequence before rendering.
- **Markdown renders code blocks unstyled.** `rehype-shiki` not wired; add it.
- **Metric delta overflows on long metric names.** Shorten or wrap — e.g., "ROC-AUC (RF)" truncation.
- **PR link is broken.** Backend sent a relative URL — fix backend to always send absolute.

## Planned — hypothesis-filter integration (F5)

When `state.selectedHypothesisId` is non-null (see
[hypothesis_board.md](hypothesis_board.md#planned--click-to-filter-f5)):

- Sections whose underlying findings or checks reference only other
  hypotheses are dimmed, not hidden — the dossier always reads as a
  complete narrative even under a filter.
- A small `× Filtering by: <hypothesis name>` chip appears at the top.
- The PR link and metric delta are always visible regardless of
  filter state.

## Known gaps / corner cases

- **MAJOR — empty dossier returns `null` so the pane vanishes.**
  Before any dossier event fires, users see the pane completely
  disappear. The spec's "Empty state" wireframe above must actually
  render — ship it as a `<section>` with the waiting text visible.
- **MINOR — no keyboard nav on section headings.** If sections
  collapse/expand in a future refactor, headings must be
  keyboard-toggleable.

## Open questions / deferred

- "Copy dossier as markdown" button: high value for judges who want to quote from it. Day 5 if time.
- Export as PDF: `DEFERRED`.
- Scroll-sync with a mini-TOC: nice but not MVP.
