# ADR-0025 — `UI_STATES.md` is the state authority; the mockups are the populated-state reference

**Status:** Accepted · 2026-10-16
**Context:** phase 0 audit · affects `AGENTS.md`, [`docs/specs/006-frontend.md`](../specs/006-frontend.md), `docs/BUILD_PLAN.md` phase 3, `docs/SCREENS.md`, `docs/agents/spydra-frontend.md`, `docs/agents/spydra-reviewer.md`

---

## Context

`AGENTS.md` says, in bold, "**The mockups in `design/mockups/` are the UI
specification.**" Spec 006 opens with the same sentence, `docs/README.md`
repeats it, and `spydra-frontend`'s own description tells the role to build to
match the mockups exactly. That was the right instruction when the mockups
were the only UI artifact.

They are not any more. `docs/UI_STATES.md` enumerates, per component and per
screen, the loading, empty, filtered-empty, error and partial states — and
**the mockups contain none of them.** Every page under `design/mockups/` is
drawn populated. A component built faithfully against a mockup is therefore
complete in exactly one of its four mandatory states, and the other three get
invented during implementation, one developer's taste at a time. That is the
failure `UI_STATES.md` was written to prevent.

The file was also, until this ADR, **referenced by nothing**: not
`BUILD_PLAN.md`, not spec 006, not `SCREENS.md`, not `docs/README.md`, and not
either of the two agent roles that would have to read it. Its own §6 asserts
that the reviewer reads it to know what is missing and that phase 3 components
are built against the matrix rather than against a populated screenshot.
Neither was wired. Left alone, phase 3 would have been built against the
mockups and the matrix discovered afterwards — which is the same cost as not
having written it.

Three shapes were considered:

1. **Fold the states into the mockups.** Correct in principle, and roughly 36
   more static HTML pages to draw and keep in sync by hand. The mockups have
   no build step on purpose; that property is what makes them trustworthy,
   and it is also what makes them expensive to multiply.
2. **Fold the states into spec 006 §2.** Puts the matrix behind a spec that is
   already long, and buries a per-screen table inside a document organised by
   structure rather than by screen. The reviewer needs the per-screen view.
3. **Name both files, with an explicit precedence rule.** Two files to read
   before building a screen, each authoritative over a different axis.

## Decision

**The UI specification is two files, and they do not overlap.**

1. **`design/mockups/`** is authoritative for **layout, spacing, typography
   and colour, in the populated state.** It stays static HTML with no build
   step, and it stays the thing a component is compared against for
   appearance.
2. **`docs/UI_STATES.md`** is authoritative for **which states exist and what
   each must not do** — §1's four mandatory states and the partial fifth,
   §3's component variant matrix, §4's per-screen states.
3. **Where the two disagree, `UI_STATES.md` wins.** It is newer, and the
   mockups are silent rather than contradictory on every axis it covers.
4. **A component or screen PR that ships only the populated path is
   incomplete**, not a PR with a follow-up. `spydra-reviewer` reads the matrix
   and reports each missing state as its own finding.
5. **Phase 3's UI tasks carry state coverage in their definition of done.**
   The two assertions `UI_STATES.md` §6 names — skeleton heights asserted
   against `--sp-row-comfortable`, and an SSE reconnect test asserting
   backfill from `Last-Event-ID` — are phase 3 acceptance on tasks `3.9` and
   `3.16`, not phase 5 hardening.

### Scope of the matrix within phase 3

`UI_STATES.md` §4 covers all ten screens, but screens 5, 9 and 10 are not
phase 3 work (`4.8`, `5.8`, `4.12`). §6's instruction to build phase 3
against the matrix is therefore scoped to the screens phase 3 actually
builds.

**`3.9` builds the shared sets; screen-specific sets land with their screen.**
This needs stating precisely, because `3.9` previously meant the fourteen
components in spec 006 §2 and the matrix makes it fifty-one — and because the
rule `3.9` exists to enforce ("screens built before their components produce
ten one-off layouts that drift") is not satisfied by deferring components
loosely.

The dividing line is **how many screens consume a set**:

- a set used by **three or more screens** is built in `3.9`, before any screen
- a set used by **one or two** is built in the task for its screen, still
  before that screen renders, so the drift rule holds at screen granularity

Applied once, that produces the lists below. **The lists are the contract, not
the rule** — a later agent reads the list rather than re-deriving it from the
screen count, because re-deriving invites exactly the per-agent judgement this
ADR is trying to remove.

`3.9` — all seventeen §3a variant completions (the components the mockups
already show, which need their missing states), plus twenty §3b sets:

- the nine table sets — header cell, row, row skeleton, checkbox, bulk action
  bar, pagination, row action menu, filter chip, search field (screens 1, 2,
  5, 7, 8)
- the seven state and feedback sets — skeleton, spinner, empty state, error
  state, toast, modal, tooltip (every screen)
- `Select` and `Toggle` (filters on 1, 7, 8; forms on 2, 3)
- `Stat strip counter` (1, 6, 7, 9) and `Line chart` (6, 7, 9)

The remaining fourteen §3b sets land with their screen instead:

| Set                                              | Task                    |
| ------------------------------------------------ | ----------------------- |
| Numeric stepper · Dropzone · Validation row      | `3.13` seeds            |
| Diff row                                         | `3.12` domain detail    |
| Segmented control                                | `3.14` template review  |
| Log line · Countdown                             | `3.16` run monitor      |
| Price history chart · Image thumbnail            | `3.18` products         |
| Chat message · Provenance badge                  | `4.12` authoring chat   |
| Selection overlay · Keycap · Ancestor breadcrumb | `6.10` playground modes |

Two of those placements are judgement rather than arithmetic. `Select` and
`Toggle` are listed in §3b under _Forms — screens 2, 3_, which by a literal
reading would defer them; they are in `3.9` because filters and preferences
put them on most screens, and a table filter bar built without a `Select` is
the drift the rule is about. Recorded here so the next reader sees a decision
rather than an inconsistency.

### Consequence this forces elsewhere

`UI_STATES.md` §1 requires a **partial** state on the Domains counter strip —
five numbers and one dash, not a whole-screen error. Spec 011 §5 returns
`"counts"` as flat numbers, which cannot express a single failed counter, so
the state is unbuildable as specified. Spec 011 §5 is amended by this ADR to
make each counter nullable, and the SPA renders `null` as the unavailable
tile. This is a generated-type change (`schema.ui.d.ts`), which is why it is
recorded here rather than left as a frontend detail.

## Cost

- **Two documents to read before building a screen, not one.** The reviewer
  carries both, and a contradiction between them is now possible in a way it
  was not when there was a single source. Mitigated by the precedence rule
  being one sentence, and by `SCREENS.md` and spec 006 pointing at both.
- **`AGENTS.md`'s bolded sentence becomes two sentences.** The anchor file
  gets slightly longer, against its own stated preference for brevity.
- **Every counter in `/api/ui/overview` becomes `number | null`**, so every
  consumer narrows before rendering. That is the honest shape — a counter
  whose query timed out has no number — but it is friction on the common path
  where all six resolve.
- **The matrix can now rot.** A file nothing referenced could not go stale in
  a way that mattered; a binding one can. Nothing checks it mechanically: a
  missing state is caught by review, not by `make check`.
- **`3.9` is still the largest task in phase 3** at thirty-seven sets, and the
  split means a reviewer has to know which list a set is on. The lists are in
  this ADR rather than spread across the screen tasks for that reason, and
  BUILD_PLAN `3.9` points here instead of restating them.
- **Fourteen sets are built against one or two screens**, so their props are
  fitted to those screens and a third consumer may need them widened. That is
  the accepted trade for not designing twenty component APIs with no caller —
  see the alternatives.

## Alternatives rejected

- **Leaving the mockups as the sole specification.** The states would be
  invented per component. This is the status quo the audit found and the
  reason for the ADR.
- **Drawing the ~36 missing state frames as mockups** (option 1 above).
  Right in principle; the hand-maintenance cost is the objection, and it
  duplicates a matrix that already exists in text.
- **Making `UI_STATES.md` authoritative over layout too**, retiring the
  mockups. The mockups are accurate down to spacing and colour, and a
  Markdown table is not a substitute for that. Both axes have an artifact
  that suits them.
- **`3.9` builds all fifty-one sets before any screen renders.** The faithful
  reading of the rule, and rejected on two counts: twenty of those sets would
  be designed with no caller, so their props would be guesses that the first
  real screen rewrites; and a single fifty-one-set task is not reviewable as
  one unit, so it would have to be split into numbered sub-tasks anyway. If
  that split is ever wanted, this is the alternative to revisit.
- **Scoping `3.9` to "the sets screens 1–4 force into existence"** — the first
  wording of this section. Rejected after counting: phase 3 builds screens 1,
  2, 3, 4, 6, 7, 8 and schedules, so roughly thirty of the thirty-four new
  sets are phase-3 work regardless. That line deferred about four sets and
  left an ambiguous boundary in exchange, which is the worst of both.
