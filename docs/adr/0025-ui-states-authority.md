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
builds. Likewise `3.9` builds the §3b component sets that screens 1–4 force
into existence; the remainder arrive with the screens that need them, rather
than as one 51-set component phase.

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
