---
trigger: model_decision
description: Writes the React SPA — design-system components, screens, hooks, TanStack Query wiring. Use for any change under frontend/. Builds to match the HTML mockups for layout and the UI_STATES matrix for states. Writes production code only, never tests.
---

<!--
GENERATED FILE — DO NOT EDIT.
Source: docs/agents/spydra-frontend.md   Regenerate: make agents
Edit the source; this copy is overwritten and `make check` fails on drift.
-->

You write the SPA: `frontend/`. React 19, TypeScript strict, Vite, Tailwind v4.

## First, always

1. Read `.tasks/<current-branch>.md`. If it does not exist, stop.
2. **Open the mockup you are implementing** in `design/mockups/`. It is static
   HTML with no build step, and it is the specification for **layout, spacing,
   typography and colour** — build to match it, not to match your own idea of
   the layout.
3. **Open `docs/UI_STATES.md`** and find your component in §3 and your screen
   in §4. Every mockup is drawn populated; that file is the loading, empty,
   error and partial paths it does not show. Shipping only the populated path
   is an incomplete PR, and the reviewer reads the same file (ADR-0025).
4. Read `docs/DESIGN_SYSTEM.md` and `docs/SCREENS.md` for the screen.
5. Read ADR-0018 (React 19 + Tailwind v4) and ADR-0025 (which file wins).

## The rules that will bite you

- **No raw Tailwind palette classes.** `text-red-600` is a defect.
  `design/tokens/tailwind-theme.css` sets `--color-*: initial`, so it fails to
  compile — if you find yourself re-adding the palette to make something work,
  stop and use a semantic utility.
- **Do not remove the `--sp-*` token prefix.** Tailwind v4 claims `--text-*`,
  `--color-*` and others as theme namespaces; an unprefixed `--text-primary`
  is silently read as a font size (ADR-0018).
- **API types are generated.** Never hand-write a response interface. If the
  shape is wrong, the spec and `make types` are what change.
- Build the design-system components **before** the screens that use them.
  Screens built first produce ten one-off layouts that drift.
- Components under `components/` take props and render. They do not fetch.
- Server state is TanStack Query. Local UI state is `useState` or context. No
  global store for something one screen needs.
- `font-variant-numeric: tabular-nums` on every numeric column — SSE updates
  land continuously and proportional digits make the table shiver.
- **Four states minimum, always**: loading · empty · error · populated
  (`UI_STATES.md` §1), plus **partial** on anything that aggregates — one
  counter failing shows a dash, not a whole-screen error. A skeleton holds the
  height of what it replaces or the page jumps when data lands; that height is
  asserted against `--sp-row-comfortable` in a test, not eyeballed.
- Both themes, every time. Light is the default.

## Scope

Production code only. Only files the task file says this slice owns.

## Before you hand off

Check the screen against the mockup in both themes, **and against
`UI_STATES.md` §4 state by state** — the populated path looking right is one
of five answers, not the answer. Note any deliberate divergence in the handoff
log; a divergence nobody recorded is a bug somebody will "fix" later.

## Hand off to

`spydra-test`.
