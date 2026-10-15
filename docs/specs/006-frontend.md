# 006 — React application

**Phase 3** · depends on 005, 011 · ADR-0013, ADR-0015, ADR-0018

The UI specification is **`design/mockups/`**. Those pages are static HTML,
open from disk with no build step, and are accurate down to spacing and
colour. Build components to match them. `docs/SCREENS.md` says what each
screen is for; `docs/DESIGN_SYSTEM.md` holds the tokens and rules.

---

## 1. Structure

```
frontend/src/
  api/
    schema.crawler.d.ts  GENERATED from the Python OpenAPI. Never hand-edit.
    schema.ui.d.ts       GENERATED from the Fastify OpenAPI. Never hand-edit.
    client.ts            thin typed fetch wrapper over both
    queries.ts           TanStack Query hooks, one per endpoint
  components/        design-system components; props in, markup out, no fetching
  views/             one per screen in docs/SCREENS.md
  hooks/             useTheme, useSSE, useUrlFilters
  lib/               formatters, url helpers
  styles/
    tokens.css       imported from design/tokens — do not fork it
    theme.css        3 lines: @import tailwindcss, tokens.css, tailwind-theme.css
```

Components do not fetch. Views compose components and own the queries. This
is the only structural rule the frontend needs and it is worth enforcing.

## 2. Components to build

From `docs/DESIGN_SYSTEM.md`. The Figma library has all of these; the mockup
CSS class in brackets is the reference implementation.

| Component | Mockup class | Notes |
| --- | --- | --- |
| `AppShell` | `.app` | Sidebar + topbar; the only layout component |
| `DomainStatePill` | `.pill` | Six lifecycle states |
| `SelectorField` | `.selector-field` | Editable selector, live resolved value, match count |
| `PagePreview` | `.preview-frame` | Sandboxed iframe, active selector outlined |
| `SampleMatrix` | `.sample-grid` | Per-field × per-URL pass/fail |
| `ValidationBadge` | `.pill` + count | |
| `ProgressBar` | `.progress` | Stacked segments, **never a percentage** |
| `Sparkline` | `.spark` | Hand-written SVG, seven points |
| `Confidence` | `.confidence` | Four bars; count carries signal as well as colour |
| `DataTable` | `.table-wrap` | TanStack Table, headless |
| `MetricTile` | `.metric` | Links to the filtered rows behind it |
| `Banner` | `.banner` | info / warning / danger |
| `Tabs` | `.tabs` | Within-screen only, never navigation |
| `ObservationTimeline` | — | Recharts; marks template-version changes |

## 3. Rules that matter in this UI

- **`tabular-nums` on every numeric column.** SSE updates land continuously
  and proportional digits make the whole table shiver.
- **Monospace for selectors, URLs and log lines.** The review screen asks for
  character-level reading.
- **URLs truncate in the middle** — the path tail is the distinguishing part.
- **A changed value flashes once (400 ms) and settles.** Nothing slides.
- **Filter and sort state lives in the URL.** When a run surfaces 40 broken
  pages the operator wants to send themselves that exact view, not rebuild it.
- **Light is the default theme.** Resolve it in an inline `<head>` script
  before first paint so dark never flashes white; respect
  `prefers-color-scheme` on first visit only, then the stored choice wins.
  Wrap every `localStorage` access in try/catch — it throws in a private
  window and the app must still render.
- **No raw Tailwind palette classes.** `tailwind-theme.css` sets
  `--color-*: initial` before declaring the semantic set, so `text-red-600`
  does not compile. This is the only thing making "colour carries state"
  structural rather than aspirational — verify it survives any Tailwind
  upgrade by writing `bg-red-500` and checking the build fails.
- **Design tokens are `--sp-*` prefixed** and the Tailwind utilities are
  named in `DESIGN_SYSTEM.md § Utility reference`. `text-secondary` from the
  old v3 config is now `text-ink-muted`.

## 4. Data and state

- **TanStack Query owns all server state.** Query keys are namespaced by
  origin — `['crawler', 'domains', filters]`, `['ui', 'schedules']` — because
  there are two backends and a key collision between them would be a very
  confusing bug. Mutations invalidate the narrowest key that covers the change.
- **The Domains screen makes one request**, to `/api/ui/overview` (spec 011
  §5), not four to the crawler API. That endpoint is why the BFF exists.
- **No global store.** Theme is context. Everything else is a URL param or
  component state.
- **SSE is a hook, not a query.** `useRunEvents(runId)` opens an `EventSource`,
  reduces events into local state, and writes the summarised result into the
  Query cache so other components see it without re-fetching.
- Optimistic updates only for pause/resume, which are instant and reversible.
  Never for approve — approval has consequences and should show the server's
  answer.

## 5. The template review screen

The screen the operator spends most of their time in (`docs/SCREENS.md` §4),
and the one to build properly even in phase 3 when selectors are still
hand-written.

Three panes: preview (45%), fields (35%), samples (20%).

- Selector edits re-resolve on a **300 ms debounce against the
  already-loaded DOM** — no network round-trip. Parse the sample HTML once
  into a `DOMParser` document and query it client-side.
- Hovering a field outlines every element its selector matches, in place.
- A toggle switches the preview to the **DOM skeleton** — what the model
  actually saw. This tells the operator whether a wrong proposal was misled or
  just mistaken.
- **The sample strip is the feature that makes this screen worth building.** A
  cell turns red the moment a selector stops resolving on any sample, before
  anything is approved.
- **Batch mode is the same screen, re-rendered.** The grid and the single view
  read the same verified-proposal payload; "open full review" expands a row in
  place. They are not two screens, and building them as two is how they drift.

## 6. Accessibility

- WCAG AA for body text, AAA for state pills.
- Visible focus ring (2 px brand, 2 px offset) on every interactive element.
  The review screen is operated from the keyboard more than the mouse.
- Tables use real `<table>` semantics. Sort controls are buttons in `<th>`.
- Live regions for SSE updates are `aria-live="polite"`, and the live log is
  **not** a live region — it would flood a screen reader.
- All motion respects `prefers-reduced-motion`.

## 7. Acceptance

- [ ] Every screen matches its mockup at 1440 px in both themes.
- [ ] `tsc --noEmit` clean with `strict` and `noUncheckedIndexedAccess`.
- [ ] No `any` in `src/` (ESLint rule, not convention).
- [ ] Both generated schema files are untouched by hand (CI checks
      `make types` is clean).
- [ ] Writing `bg-red-500` fails the build.
- [ ] No `forwardRef` in the codebase — React 19 passes `ref` as a prop.
- [ ] Dark theme does not flash on load.
- [ ] Reloading a filtered table view restores the same rows from the URL.
- [ ] Closing and reopening the run monitor mid-run backfills, with no gap.
- [ ] Keyboard-only traversal of the review screen can edit and approve.
- [ ] Vitest covers the reducers and hooks; Playwright covers seed → propose →
      approve → run → inspect.
