# 0043 — Storybook is the component workshop, never a fourth spec artifact

**Status:** Accepted · 2026-10-24
**Supersedes:** nothing

## Context

Task 3.9 delivered the coded design-system library: thirty-one components in
`frontend/src/components/`, props in / markup out. Three artifacts already
specify the UI (ADR-0031): `SCREENS.md` (which screens exist), the Figma file
(how every state looks) and `UI_STATES.md` (which states must exist). The
library needed a place where a human can see all thirty-one components side by
side, in both themes, without booting the app — and CI needed a way to notice
when a component's rendering changes unintentionally.

## Decision

**Storybook 10.6** (the unified `storybook` package plus `@storybook/react-vite`)
is the component workshop for the coded library, colocated as
`*.stories.tsx` beside each component. **Chromatic** publishes the story set
for visual regression; the CLI runs in the `web` container via `make chromatic`
against a prebuilt `storybook-static/`. Source viewing is the built-in **Code
Panel** (`parameters.docs.codePanel` in `preview.tsx`) — `@storybook/addon-storysource`
was removed upstream in Storybook 9 and installing its 8.x release against v10
would be a defect. Dark-theme review is a `theme` toolbar global whose decorator
sets `data-theme` on the canvas iframe's `documentElement`, because the dark
tokens are scoped `:root[data-theme="dark"]` and a wrapper div cannot match
them.

## What it must never become

- **A fourth UI-spec artifact.** Three spec artifacts exist (ADR-0031) and
  Storybook is not one of them. The variant matrix stays in `UI_STATES.md` §3;
  stories mirror the matrix arms (the `components-{3a,3b}` test enumeration)
  and cite it — they never redefine it. A divergence between a story and
  `UI_STATES.md` is fixed in the story.
- **A test suite.** Stories are documentation; `make test-web` is unaffected
  and the portable-stories/vitest integration is deliberately not adopted. A
  story that starts asserting things is a test in the wrong place.
- **Part of `make check`.** `storybook build` is minutes, not seconds. CI
  builds the workshop and runs Chromatic in a step after `make check`, guarded
  on `CHROMATIC_PROJECT_TOKEN` — absent the token the gate is unchanged.

## Cost

Four dev-dependencies in `frontend/` and a CI step that publishes to an
external service; until the human creates the Chromatic project and accepts a
baseline, that step is advisory (`--exit-zero-on-changes`). Hover/focus/pressed
arms have no stories — they are CSS utilities, not props, and faking them with
interaction code would test the fake. Dark-theme Chromatic coverage is deferred
(toolbar covers human review); the default light global is what gets captured.

Tooling-only: no runtime dependency is added to any image, so ADR-0017's
wheel-readiness gate does not apply. Installation and every operation stay
Docker-native (ADR-0010) — `make storybook`, `make storybook-build`,
`make chromatic`.
