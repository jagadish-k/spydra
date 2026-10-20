# ADR-0031 — Figma is the drawing authority; `SCREENS.md` is the screen registry

**Status:** Accepted · 2026-10-20 · **§Consequences corrected by
[ADR-0032](0032-everything-above-a-primitive-is-a-component.md)** — this ADR
attributed the hand-drawn screen elements to the frames being "behind". The
actual cause was that no component in the library had a single TEXT property,
so an instance could not carry its own content.
**Extends:** [ADR-0025](0025-ui-states-authority.md) — its two-axis split
stands; this adds the third artifact it could not name
**Affects:** `AGENTS.md`, [`docs/SCREENS.md`](../SCREENS.md),
[`docs/UI_STATES.md`](../UI_STATES.md), [`docs/COMPONENTS.md`](../COMPONENTS.md),
[`docs/specs/006-frontend.md`](../specs/006-frontend.md), `docs/DESIGN_SYSTEM.md`,
`docs/BUILD_PLAN.md` phase 3, `docs/deck/index.html`,
`docs/agents/spydra-frontend.md`, `docs/agents/spydra-reviewer.md`

---

## Context

ADR-0025 split the UI specification across two artifacts — `design/mockups/`
for populated layout, `docs/UI_STATES.md` for which states exist — and that
split was correct. It was also incomplete, because **a Figma file existed at
the time and ADR-0025 does not mention it.** Neither does `AGENTS.md`, nor
spec 006 beyond one passing clause, nor `SCREENS.md`.

That omission has cost four separate audit passes, each of which rediscovered
the same ambiguity and reached a different conclusion. The proximate causes,
measured rather than inferred:

1. **`get_metadata` with no `nodeId` reports only the pages currently loaded
   in the editor.** On 2026-10-20 the same file answered **two pages** (`📘
Cover`, `🧩 Components`) to that call and **four pages** (adding `🎨
Foundations` and `🖥 Screens`) to `figma.root.children` through the Plugin
   API, minutes apart. An agent that inventories the file with the obvious
   tool gets a result that depends on where the operator's cursor was. One
   pass concluded from this that the Screens page had been deleted. It had
   not; node `7:2` resolved fine the whole time.
2. **Nothing stated the screen count in a way that survived re-derivation.**
   `SCREENS.md` said ten and was right; Figma shows eleven top-level frames
   and `design/mockups/` eleven screen files, because screen 4's Select mode
   is a layout too different to be a variant and so gets its own artifact in
   both. Three artifacts, two counts, no reconciliation written down. Every
   pass re-counted and half of them reported a missing eleventh screen.
3. **The two candidate authorities each named the other.** ADR-0025 names the
   mockups; the Figma Cover frame reads _"Source of truth: the repo at
   projects/personal/spydra … nine static screens in `design/mockups`"_ — a
   third count, and circular.
4. **`.tasks/design-figma-states.md` deferred the decision** — "`design/mockups/`
   was going to be retired in favour of Figma … Decide before phase 3, not
   during" — and the decision was never made, so the ambiguity was load-bearing
   rather than incidental.

Meanwhile Figma had quietly become the most complete artifact in the project.
Its `🖥 Screens` page holds **56 frames** which match `UI_STATES.md` §1
exactly: eleven populated, eleven loading, eleven error, fifteen empty (both
sub-cases on screens 1 · 5 · 7 · 8), four partial (1 · 6 · 7 · 9) and four
dark (1 · 4 · 6 · 10). No gaps and no extras across the ten screens it
covers. The artifact the documentation did not name was the only one that had
done the work — and because it was unnamed, nobody noticed that the one
screen it does **not** cover, Schedules, has no design anywhere.

## Decision

**Three authorities, one axis each, and a registry that owns identity.**

1. **`docs/SCREENS.md` is the screen registry.** It is the single source of
   truth for which screens exist, how many there are, and where each is
   drawn. Its table carries, per screen, the Figma node id, the mockup file,
   the spec, the build-plan task and the frame count. **No other document
   enumerates screens.** A document that needs a screen list links to the
   registry; a screen built without a row in it is the defect.
2. **Figma `🖥 Screens` is authoritative for what every state looks like** —
   layout, spacing, typography and colour, in **all** states, not only
   populated. This is the change from ADR-0025 clause 1.
3. **`docs/UI_STATES.md` stays authoritative for which states must exist and
   what each must not do** — ADR-0025 clause 2, unchanged.
4. **`design/mockups/` is a runnable reference, not an authority.** It keeps
   its place because it renders in a browser with the real tokens and no
   Figma account, which is worth having; it shows one state of eleven, which
   is why it no longer decides anything. **Where it and Figma disagree, Figma
   wins.** Each file carries a header saying so.
5. **`docs/COMPONENTS.md` is the component catalog**, read from the Figma file
   rather than from the specs, and carries the per-screen usage matrix and the
   reconciliation against `UI_STATES.md` §3.
6. **Precedence, where any two disagree:** `UI_STATES.md` on whether a state
   must exist → Figma on what it looks like → `SCREENS.md` on whether the
   screen exists at all. The registry wins on identity because identity is
   the thing that kept drifting.
7. **Never inventory the Figma file with a bare `get_metadata`.** Enumerate
   pages with `figma.root.children` through `use_figma`, then query per page.
   This is a correctness rule, not a style preference: the bare call returns
   a different answer to the same file depending on editor state.

### Two open defects, recorded rather than resolved

Both are in the registry so that they are visible, and neither is resolved
here because both need a decision this ADR should not make silently.

- **The Schedules screen has a complete backend spec and no design.** Spec
  011 does the backend properly: `ui.schedules` and `ui.schedule_fires` (§1),
  the once-only fire loop (§3), six endpoints (§4), five acceptance criteria.
  `3.11` builds the screen, and ADR-0025's own alternatives section counts it
  as phase 3 work — so it is intended, not a stray line. But there is **no
  section in `SCREENS.md`, no mockup, no Figma frame and no row in
  `UI_STATES.md` §4.** It is the only screen in the project with no state
  matrix, which is precisely the failure `UI_STATES.md` was written to
  prevent. **Design it or defer `3.11` before phase 3 starts.** Registering
  the gap as row 11 of the registry is this ADR's contribution; closing it
  is not.
- **Screen 4's Skeleton mode is drawn nowhere.** `UI_STATES.md` §4 gives
  screen 4 three modes and spec 014 §6 makes Skeleton the escape hatch for
  content behind a click. `6.10` builds it and has no reference to build
  against. `4.10` _also_ claims DOM-skeleton mode, so two tasks own one mode;
  that duplication wants resolving in the phase 4 and 6 spec passes.

## Consequences

- **The recurrence stops at its mechanism, not its symptom.** Clause 7 is the
  one that matters. Renaming documents would not have helped; an inventory
  tool that lies intermittently would have re-created the confusion against
  any naming scheme.
- **`docs/COMPONENTS.md` reports 39 components against §3's 51**, and the
  difference is not subtraction: five components exist under a different name
  than §3 gives them (`Keycap`→`Kbd`, `Selection overlay`→`Screenshot
viewport`, `Log line`→`Log row`, `Table row skeleton`→`Skeleton Shape=Row`,
  `Stat strip counter`→`Metric tile`). A name-based audit reports all five as
  missing, and three previous passes did.
- **Sixteen components are hand-built inside screen frames** that the library
  already has as sets — table rows, headers, pagination, nav items, the
  segmented control, the screenshot viewport, chat messages, log rows, domain
  cards, toasts, select, toggle, checkbox, card, icon, kbd. A developer
  building screen 1 from frame `7:2` will hand-roll a table row because that
  is what the frame shows. **ADR-0032 supersedes the explanation given here:**
  the frames were not "behind" — they were the only thing the library made
  possible, because no component had a TEXT property. Six of the sixteen are
  now closed; `COMPONENTS.md` §2 carries the rest.
- **`Metric tile State=unavailable` is contradicted by drawn frames.** The
  five Partial frames exist and were drawn with an overridden em dash, so the
  component and the frames disagree today. Adding the variant is `3.9` work;
  the frames should then instance it.
- **The mockups will drift**, and that is accepted. A non-authoritative
  reference that lags is a known-stable arrangement; two authorities that
  disagree is not. `make check` does not gate the mockups, so the drift is
  cheap and visible rather than cheap and hidden.
- **Figma becomes a dependency for UI work.** A developer without file access
  can no longer get an authoritative layout from the repo. This is the real
  cost of clause 2 and it is paid knowingly: the alternative is 45 more
  hand-maintained HTML pages, which ADR-0025 already rejected on cost.

## Alternatives rejected

- **Retire `design/mockups/` entirely**, which is what the deferred question
  asked. Rejected: `playground.html` is the only runnable reference for spec
  014's canvas, the pages cost nothing to keep, and they are the fallback
  when Figma is unreachable. Demotion gets the correctness benefit without
  deleting a working artifact. **Revisit this if the mockups are ever found
  to have misled someone** — that is the signal that the drift stopped being
  cheap.
- **Make `design/mockups/` authoritative and draw the 45 missing state pages
  there.** ADR-0025 rejected this on hand-maintenance cost and that reasoning
  is unchanged; Figma has since drawn all 56 for free.
- **Keep Figma unnamed and let `UI_STATES.md` carry layout too.** ADR-0025
  rejected this correctly — a Markdown table is not a substitute for spacing
  and colour. It is also now moot: the frames exist.
- **Put the registry in a new `docs/SCREEN_REGISTRY.md`.** A fourth file
  about screens, to fix a problem caused by three files about screens.
  `SCREENS.md` already owned screen identity in practice; it is now
  authoritative for it in writing.
- **Generate the registry from the Figma file in `make check`.** Attractive,
  and the right eventual answer. Rejected for now because it makes the gate
  depend on a network call and a Figma token, and because the registry has to
  record things Figma does not know — the spec, the build-plan task, and the
  two open defects above. Worth revisiting as a `make` target that _diffs_
  rather than generates.
