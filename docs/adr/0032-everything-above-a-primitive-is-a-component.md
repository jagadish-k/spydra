# ADR-0032 — Everything above a primitive is a component

**Status:** Accepted · 2026-10-20
**Extends:** [ADR-0031](0031-figma-is-the-drawing-authority.md) — Figma is the
drawing authority; this says what a Figma screen is allowed to contain
**Affects:** `AGENTS.md`, [`docs/COMPONENTS.md`](../COMPONENTS.md),
[`docs/SCREENS.md`](../SCREENS.md), [`docs/UI_STATES.md`](../UI_STATES.md),
[`docs/specs/006-frontend.md`](../specs/006-frontend.md), `docs/BUILD_PLAN.md`
phase 3, `docs/agents/spydra-frontend.md`, `docs/agents/spydra-reviewer.md`

---

## Context

ADR-0031 made the Figma file authoritative for what every state looks like.
That only helps if a screen frame is a composition of named components. It was
not. Sixteen components that the library already held were drawn by hand
inside the screen frames instead of being instanced — table rows, header
cells, pagination, nav items, the segmented control, the screenshot viewport,
chat messages, log rows, domain cards, toasts, select, toggle, checkbox, card,
icon and kbd.

ADR-0031 recorded this and attributed it to the frames being "behind". **That
attribution was wrong, and the real cause matters**, because it is the thing
that would have made this ADR unenforceable:

> **Not one of the 39 components had a single TEXT property.** Every component
> exposed `VARIANT` properties only. An instance therefore could not carry its
> own content: every `Button` instance read "Button", every `Table row`
> instance showed the same placeholder cells.

A library with no text properties **cannot** compose a content-bearing screen.
Hand-drawing the rows was not sloppiness; it was the only way to draw a screen
at all. A rule saying "use components" issued against that library would have
been ignored within a day, correctly.

Two file-wide defects followed from the same cause and had gone unnoticed
through four audits:

- **The sidebar's active row was baked in.** `App shell/Sidebar` was a single
  component with `nav/Domains` hard-set to the selected tokens, so **all 56
  frames showed "Domains" as the current screen** — including Run monitor,
  Products and Reports. Its nav rows were hand-drawn frames, which is why the
  `Nav item` component had zero usages.
- **The topbar breadcrumb was baked in**, so all 56 frames read
  "Spydra / Domains".

Neither is visible when you look at one frame. Both are obvious the moment a
screen is composed from components, because then the question "which one is
active?" has to be answered by a property.

## Decision

**Cardinal rule: in Figma, anything above a primitive is a component on the
`🧩 Components` page, and a screen frame is a composition of instances.**

1. **A screen frame contains instances and layout, nothing else.** If a
   visual element has state, variants, repetition, or an identity a developer
   would name — a row, a pill, a badge, a nav item, a toast, a card, a
   control — **it is a component**, and the frame holds an instance of it.
2. **Primitives are the exception, and the list is closed:** a layout
   container (frame, auto-layout, spacer, divider), a text node, and the page
   scaffolding that positions them. A bordered surface used purely to group is
   layout. Anything else is a component.
3. **Every component carries the properties its content needs.** A component
   with only `VARIANT` properties and no `TEXT` property is incomplete,
   because it forces the hand-drawing this rule prohibits. Adding the variants
   without the text properties is how this library got into the state ADR-0031
   found.
4. **No component may hard-code which of its children is selected, current or
   active.** That is a property or a variant axis. `App shell/Sidebar` now has
   an `Active=` axis with one value per destination, and every screen frame
   sets it.
5. **A hand-drawn element that duplicates an existing component is a review
   finding**, reported by `spydra-reviewer` like any other defect, not a style
   preference.
6. **Screen 11 Schedules is the worked example.** It was drawn after this rule
   and contains no hand-drawn component: shell, metric tiles, inputs, selects,
   table header cells, schedule rows, fire rows, pagination, empty, error and
   skeleton states are all instances.

### What this cost to make true

The rule was unenforceable until the library could carry content, so the
enabling work landed with it:

- `TEXT` properties added to **Button** (`Label`, across 48 variants),
  **Tag** (`Label`), **Input** (`Text`), **Table header cell** (`Label`),
  **Metric tile** (`Label`, `Value`, `Detail`) and **Pagination** (`Summary`).
- **`Nav item` rebuilt** as `State` × `Badge` (9 variants) with `Label` and
  `Count` text properties. Its previous `Count=Badge` axis carried only the
  green tone, which would have silently recoloured the amber Templates and
  Unknown Pages badges. It had zero instances, so it was free to restructure.
- **`App shell/Sidebar` became a component set** with `Active=` per
  destination, its nav rebuilt from `Nav item` instances, and a `Schedules`
  row added. **`App shell/Topbar` gained a `Breadcrumb` text property.** All
  57 frames were then set to their own active row and breadcrumb.
- Three new components for screen 11: **`Schedule state`** (Enabled · Paused),
  **`Schedule row`** (6 text properties) and **`Fire row`** (fired · skipped ·
  failed, reusing `Tag` for the outcome).

**Adding a text property can silently reset an existing instance's override.**
It did, five times out of 300 — three `Input` placeholders and two
`Metric tile` values. They were caught only because the 300 overrides were
captured before the change and compared after. **Any future property addition
captures a baseline first.** This is now the procedure, not a suggestion.

## Consequences

- **`Table row` is revealed as `Domain row`.** It is hard-wired to the Domains
  table's ten columns, which is why screen 11 needed its own `Schedule row`
  rather than a variant. **A different column set is a different component.**
  Renaming `Table row` is deferred: it has no instances today, so the rename
  is free whenever someone does it, and doing it here would have widened an
  already large change.
- **Sixteen hand-drawn elements remain** in screens 1–10, listed in
  `COMPONENTS.md` §2. They are now rule violations rather than observations.
  Remediating them is **not** a cosmetic pass: each needs its component to
  gain text properties first, exactly as above, each with a baseline. That is
  a scoped task, not a drive-by, and it belongs before `3.9` builds the React
  components against these frames.
- **`Skeleton` is not size-tolerant.** Its `Shape=Card` variant has absolutely
  positioned children, so an instance resized to a metric tile's 190×96
  overflows; screen 11's loading frame clips them. `UI_STATES.md` §1 requires
  a skeleton to hold the same height as the content it replaces, so this is a
  real gap and a `3.9` item.
- **Variant counts grow.** The sidebar is now ten 240×940 variants. That is
  the price of not hard-coding the active row, and it is the standard answer;
  the alternative was a file where every screen claimed to be Domains.
- **The rule is checkable.** "Does this frame contain a frame that duplicates
  a component?" is answerable by traversal, so a future `make` target could
  assert it. Not built here — see ADR-0031's note on gates that need a Figma
  token.

## Alternatives rejected

- **State the rule and remediate later.** The rule would have been false on
  the day it was written, against a library that made compliance impossible.
  A rule nobody can follow teaches people to ignore rules.
- **Remediate all sixteen in this change.** Each needs text properties plus a
  300-override baseline and a comparison. Done in one pass it would be one
  unreviewable commit touching every frame in the file. Screen 11 proves the
  rule instead, and the rest is scoped work.
- **Give `Table row` a `Columns=` variant axis** so one component serves every
  table. The column sets share nothing but a height; the variants would differ in
  every cell. A different column set is a different component.
- **Let the sidebar's active row be an instance override per frame**, with no
  variant axis. It is what the file did by accident, and it is why every
  screen showed Domains: an override nobody sets is an override nobody
  notices.
