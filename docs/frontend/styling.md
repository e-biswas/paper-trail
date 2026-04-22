# Frontend — Styling

## Purpose

Define the visual identity and the conventions for Tailwind + shadcn/ui. Keep the look consistent across panes without locking into a design system that would slow us down.

## Status

`TODO` · last updated 2026-04-21

## Public interface

No code interface — conventions and design tokens. These apply everywhere components are authored.

## Design tokens (Tailwind)

`web/tailwind.config.js` extends the default theme with a small design-system layer:

```js
// Semantic tokens layered on top of shadcn's default HSL variables
theme: {
  extend: {
    colors: {
      status: {
        pending:   "hsl(var(--status-pending))",   // slate-500
        checking:  "hsl(var(--status-checking))",  // blue-500
        confirmed: "hsl(var(--status-confirmed))", // emerald-500
        refuted:   "hsl(var(--status-refuted))",   // rose-500
        verdict:   "hsl(var(--status-verdict))",   // amber-400
      },
    },
    fontFamily: {
      sans: ["Inter var", "ui-sans-serif", "system-ui"],
      mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular"],
    },
  }
}
```

CSS variables live in `web/src/index.css`:

```css
:root {
  --status-pending:   220 14% 46%;
  --status-checking:  217 91% 60%;
  --status-confirmed: 160 84% 39%;
  --status-refuted:   351 83% 56%;
  --status-verdict:    43 96% 56%;
}
```

Dark-mode overrides as needed.

## Theme

### Dark mode as default

The hackathon demo is recorded in dark mode — research-tool aesthetic, high contrast, easier on eyes for live demos.

- Implemented via `next-themes`-style pattern OR shadcn's built-in `ThemeProvider`.
- Toggle lives in the StatusBar.
- System-preference-aware on first load.

### Typography

- Sans for prose: Inter var.
- Mono for code, tool output, evidence snippets, metric values: JetBrains Mono.
- Loaded via `@fontsource/inter` and `@fontsource/jetbrains-mono` for self-hosting (no Google Fonts round-trip).

### Spacing scale

Default Tailwind. No custom spacing.

### Radii

- Cards: `rounded-xl` (12px)
- Chips / badges: `rounded-full`
- Buttons: shadcn defaults

## shadcn/ui setup

### Install

```bash
cd web
npx shadcn@latest init     # choose Tailwind, TypeScript, default (New York) style, CSS variables
```

`components.json` ends up at `web/components.json` with aliases pointing into `src/components/ui`.

### Components to add (MVP set)

```bash
npx shadcn@latest add button card badge tabs textarea scroll-area separator tooltip sonner
```

That's the full set we need. Don't add more speculatively.

### shadcn overrides

- Default shadcn primitives go in `web/src/components/ui/`. **Do not edit these files** — they should remain stock so we can re-generate if needed.
- Any extension goes in our own component files in `web/src/components/` and composes the shadcn primitives.

## Conventions

### Class ordering

Follow the Tailwind official ordering: layout → box → typography → visual → state. Install `prettier-plugin-tailwindcss` to enforce automatically.

### Spacing rhythm

- 8px base grid, so always multiples of `1` (4px) / `2` (8px) / `4` (16px) / `6` (24px) / `8` (32px).
- Card internal padding: `p-4` on small, `p-6` on large cards like Dossier.

### Color use discipline

- Status colors (see tokens) are the ONLY semantic colors used to convey state.
- Gray scale carries all structural hierarchy.
- Brand accent: gold (verdict color) used sparingly — only for the verdict state and the PR button.

### Animation

Respect `prefers-reduced-motion`:

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
```

Standard timings:
- Card enter: 200ms `ease-out`
- Bar fill: 400ms `ease-out`
- Verdict pulse: 2s × 3 then stop

### Icons

Use `lucide-react` (shadcn's default icon set). Import only the icons you use.

## How to verify (end-to-end)

### Visual check

1. Run the dev server. Open at 1440×900.
2. Every component uses the defined tokens (no stray hex colors in class names).
3. Dark/light toggle switches all colors cleanly (no areas that stay dark).
4. Reduce motion in OS settings; re-run; verify no animation runs.
5. Hover states consistent across all buttons / cards.
6. Typography: all body text Inter, all code/metrics JetBrains Mono.
7. Status colors match the tokens (Hypothesis Board card borders visibly differ by state).

### Lint / style checks

```bash
npm --prefix web run lint        # eslint + tailwind-merge warnings
```

## Known gaps / corner cases

- **MINOR — `strictNullChecks` absent from `tsconfig.app.json`
  despite the frontend convention requiring strict mode.**
  [web/tsconfig.app.json:18-22](../../web/tsconfig.app.json#L18-L22).
  Turn on `"strict": true` (or at least `"strictNullChecks": true`);
  the repo's TS surface is small enough that the fallout is bounded.
- **MINOR — ESLint not on the commit path.** `package.json` defines
  `lint` but there's no pre-commit hook that runs it. Add to
  `dev.sh` checks or to the preflight script (see
  [../../scripts/README.md](../../scripts/README.md)).

## Open questions / deferred

- Responsive breakpoint set for mobile: out of MVP scope.
- Logo / wordmark: `DEFERRED`; type-based wordmark is enough.
- Animated hero for the first-load empty state: `DEFERRED`.
