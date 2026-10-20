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

ADR-0031 attributed this to the frames being "behind". That was wrong, and
**the first version of this ADR replaced it with a second wrong explanation**,
which is worth recording because it nearly set the remediation cost an order of
magnitude too high.

That version said: not one of the 39 components had a TEXT property, therefore
an instance could not carry its own content, therefore hand-drawing was the
only way to draw a screen at all. The first clause is true. **The inference
from it is false, and the evidence was already in hand.** Figma lets you
override text inside an instance with no component property involved, and the
file was full of it:

| Component        | TEXT properties | Distinct strings across its instances |
| ---------------- | --------------- | ------------------------------------: |
| `Selector field` | none            |                                **68** |
| `Banner`         | none            |                                     9 |
| `Empty state`    | none            |                                     9 |
| `Error state`    | none            |                                     9 |

The 300 instance overrides captured as a safety baseline were themselves the
disproof, and they were read without being noticed.

**The real cause is structural, and duller.** `Table row` is hard-wired to the
Domains table's ten columns, so it fits exactly one of the six tables in the
app; the others had nothing to instance. Elsewhere the screen was simply drawn
before the component existed. Neither is a reason to keep hand-drawing.

**What text properties actually buy** is a named, discoverable API on the
component and overrides that survive a variant swap — real but incremental.
They are **not** a precondition for composing a screen, and this ADR does not
require them.

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

### Enabling work that landed with the rule

Not required by the rule — see above — but done, and worth keeping:

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
captures a baseline first.** This is now the procedure, not a suggestion — and
it is a reason to add text properties sparingly, since the override they
replace already worked.

## Consequences

- **`Table row` was deleted.** It was hard-wired to the Domains column set, so
  it fitted one of six tables and nothing ever instanced it. **A different
  column set is a different component**, and the app has six tables, so it has
  six row components, each reused across every frame of its screen.
- **Three library components turned out not to be violations at all.** `Card`,
  `Kbd`, `Toast` and `Toggle` are specified in `UI_STATES.md` §3b and drawn by
  no screen, so there was nothing hand-drawn duplicating them; `Screenshot
viewport` is a library specimen of the overlay mechanic rather than
  something a screen instances. The original count of sixteen violations was
  an over-count made by assuming every unused component had a hand-drawn twin.
  Checking each one against the frames is what corrected it.
- **Remediation is done.** All the hand-drawn duplicates in screens 1–10 were
  closed on 2026-10-20: six per-table row components, plus `Log line`,
  `Domain card` and `Chat message` rebuilt from the drawn elements, plus
  `Selection overlay`, `Field highlight` and `Segmented control`. 49
  components, 1,761 instances across 62 frames. `COMPONENTS.md` §3 lists the
  four containers deliberately left as frames and why.
- **Copying only text is not enough.** Replacing a drawn element with an
  instance must carry **text, text fills, nested variant properties and nested
  text**. Copying characters alone silently flattened the Domains sparkline
  colours to one value and reset every Seeds pill label to "New". Both were
  caught by rendering the frame and comparing against `design/mockups/`, not
  by reading the diff.
- **Data-driven geometry cannot be an instance override.** Figma refuses to
  move an instance child (`relative-transform`) and quietly reverts resized
  auto-layout children. The run monitor's per-domain progress bars are
  therefore 50 equal ticks whose fills are overridden. `COMPONENTS.md` §4
  carries this and two other API constraints that each cost a regression.
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
