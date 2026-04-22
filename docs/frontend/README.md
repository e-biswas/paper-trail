# Frontend — Overview

## Purpose

React + Vite + TypeScript dashboard that connects to the backend over WebSocket and renders the agent's reasoning live. Three main live panes (Hypothesis Board, Tool Stream, Dossier) driven by Deep Investigation events; a Quick Check sidebar for one-off verification. Tailwind + shadcn/ui for styling.

## Status

`TODO` · last updated 2026-04-21

## Module index

| Module | File | Status | Responsibility |
|---|---|---|---|
| App shell | [app_shell.md](app_shell.md) | `TODO` | Layout, routing (none — single page), input form, WebSocket client, global status bar |
| Hypothesis Board | [hypothesis_board.md](hypothesis_board.md) | `TODO` | Signature UI element: ranked hypotheses with live confidence bars |
| Tool Stream | [tool_stream.md](tool_stream.md) | `TODO` | Collapsible log of every tool call the agent makes |
| Dossier | [dossier.md](dossier.md) | `TODO` | Final evidence report in fixed 5-section order + PR link |
| Quick Check | [quick_check.md](quick_check.md) | `TODO` | Chat-style sidebar, 3 canned chips + free text |
| Parser + state | [parser_and_state.md](parser_and_state.md) | `TODO` | Reducer routing envelope events to panes |
| Styling | [styling.md](styling.md) | `TODO` | Tailwind + shadcn/ui setup, design tokens, dark mode |

## Shared conventions

### Directory layout (authoritative)

```
web/
├── package.json
├── vite.config.ts
├── tailwind.config.js
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx
    ├── state.ts               ← reducer
    ├── parser.ts              ← envelope routing
    ├── ws.ts                  ← WebSocket client
    ├── types.ts               ← mirrors envelope schemas from docs/integration.md
    ├── fixtures/
    │   └── replay.json        ← saved event log for offline UI dev (stretch)
    ├── components/
    │   ├── HypothesisBoard.tsx
    │   ├── ToolStream.tsx
    │   ├── Dossier.tsx
    │   ├── QuickCheck.tsx
    │   ├── StatusBar.tsx
    │   └── ui/                ← shadcn-generated primitives (Button, Card, Tabs, etc.)
    └── lib/
        └── cn.ts              ← shadcn's classnames helper
```

### TypeScript conventions

- Strict mode. `strictNullChecks: true`. No `any`.
- Mirror envelope types from [../integration.md](../integration.md) in `src/types.ts`. These types are the **source of truth on the client side** for the event contract.
- Each component exposes its props in its own `.md` under **Public interface**.
- No global state library. Plain `useReducer` + `Context` is enough.

### Component conventions

- One component per file.
- Use shadcn/ui primitives (`Card`, `Button`, `Badge`, `Tabs`, `ScrollArea`) as the visual building blocks.
- Responsive: target 1440×900 for the demo; degrade gracefully to 1024×768. Mobile is out of scope.
- No routing library. Single page, two modes toggled via Tabs or a mode switch.

### Event consumption

- Events arrive from `src/ws.ts`.
- `src/parser.ts` validates envelope shape against `types.ts`.
- `src/state.ts` reducer routes events to slices per the pane-routing table in [../integration.md](../integration.md#pane-routing-frontend-reducer-rules).
- Components read their slice via `useContext` and render.

### Visual principles

- **Liveness over prettiness.** The demo sells the "watch it think" feeling. Micro-animations on state updates (confidence bar growing, new hypothesis fading in) are high ROI.
- **Dense but scannable.** Judges need to see Hypothesis Board + Tool Stream + Dossier + Quick Check in the same viewport.
- **Dark mode default.** Research-tool aesthetic.
- **Typographic hierarchy over color.** Use monospace for code and tool output, sans-serif for prose.

## How to verify (end-to-end) — whole frontend

After all modules land:

1. `npm --prefix web run dev` boots with no type errors.
2. Browser opens `http://localhost:5173` showing the dashboard shell with the primary demo prefilled.
3. Click **Run Deep Investigation**. Hypothesis Board populates with ≥3 cards within 30s.
4. Tool Stream shows tool calls streaming in real time; each tool call is collapsible.
5. Dossier panes fill in canonical order as the run progresses.
6. On success, PR link appears at the top of the Dossier pane and opens the real PR in a new tab.
7. In the Quick Check sidebar, click a canned chip ("Is imputation fit on train only?"). A verdict card appears within 30s with file:line citations.
8. Resize the window; all panes remain legible at 1024×768.

## Open questions / deferred

- Replay mode from saved fixture: `DEFERRED` to stretch, useful for offline UI dev.
- Mobile layout: out of scope.
- Auth / login: out of scope.
- Persistence of past runs: out of scope.
