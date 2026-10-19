# docs/tidy-adrs-and-linear-plan — phases 2–6 audit

**Task:** none — asked for directly ("what about the other phases, have they
been audited?") · **Spec:** BUILD_PLAN phases 2–6 against specs 001–014 and
the ADRs · **ADRs that constrain this:** 0003 (three pools), 0004 (stop on
block), 0008 (four ports), 0012 (SSE), 0019 (one authoring pipeline), 0020
(best-of-N), 0025 (UI_STATES authority), 0027 (no required fields)

## The honest answer to the question

**No. Phases 2–6 had never been audited by anyone.** Phase 0 was re-proved
from evidence (`.tasks/chore-phase-0-audit.md`, 16 of 17 tasks re-run); phase
1 was reworked in the same commit as this file. Phases 2–6 had been read
while _writing_ phase 1 and never checked as a whole.

Ten findings. **Five are defects this branch introduced an hour earlier**,
which is the part worth sitting with: linearising phase 1 created duplicates
downstream, and nothing caught them because nothing cross-checks the plan
against itself.

## Findings — self-inflicted, fixed here

- **A1 · `1.12` duplicated `5.2` and `5.5`.** Phase 1 gained "asset queue and
  the asset gate" while phase 5 already owned `AssetGate` (spec 008). Split on
  the spec boundary instead: spec 002 §7 is scheduler behaviour (enqueue +
  backpressure, `1.12`), spec 008 is the pipeline that drains it (`5.2`).
  Building the gate in phase 1 would have been building it for no consumer.
- **A2 · Phase 1's exit claimed assets are "queued and drained".** Nothing
  drains them until `5.2`. Corrected.
- **A3 · `1.13` claimed run-event emission, which is `2.8`'s.** Phase 1's
  worker now emits none and says so; there is no consumer before phase 3.
- **A4 · `3.2` pointed at "the YAML loader from `1.12`"** after the loader
  became `1.14`. The renumber sweep grepped every file _except_ BUILD_PLAN
  itself.
- **A5 · Phase 2's exit promised fixture shapes with no task to build them.**
  Now `2.1`.

## Findings — pre-existing, fixed here

- **A6 · `AssetStore` had no task in any phase.** It is one of the four ports
  ADR-0008 names, and `5.3` implied it without naming it. Now in `5.2`, so
  storage location stays config rather than code.
- **A7 · `5.6` and `5.10` reimplemented phase-1 behaviour.** `5.6` was
  "broken-template detector — the 20% threshold halting a domain", which is
  `1.11` and cannot wait: it is the only thing between a redesign and silent
  corruption. `5.10` carried `strategy = static_fallback`, which is `1.7`.
  Both retargeted to what phase 5 actually adds — the report, the diff, the
  sizing.
- **A8 · `5.1`'s "two offline fixture domains" read as a duplicate of `1.4`.**
  They are different: `1.4` serves HTML to the crawler, `5.1` writes
  observations straight to Postgres so a fresh clone has something to look at.
  Said so.
- **A9 · Phase 2 had no done conditions and thin spec references** — five of
  nine tasks named no spec at all. Rewritten: every task carries a spec
  reference and a "Done when", and the phase is declared linear with the
  dependency that makes it so.

## Findings — filed, NOT fixed

- **A10 · The soft 404 has a fixture and no behaviour.** `1.4` ships a page
  returning HTTP 200 with no product, because a catalogue with dead links is
  ordinary. Spec 003 §3 has no answer for it: the `empty_extraction`
  predicate cannot tell it from a redesign, so dead links would move a
  healthy domain to `broken` at 20%. Whether it is a fourth `unknown_pages`
  reason, a signal excluded from the threshold, or accepted as-is is a
  decision no ADR covers. Recorded as a **decide-first** on `1.10` rather
  than invented here — rule 1.

## Not audited, and worth saying

- **Phases 3–6 were checked for contradiction, duplication and dangling
  references, not for completeness against their specs.** Phase 2 got the
  full treatment because it is next. Phases 3–6 still have the shape phase 2
  had before this pass: most tasks name a spec, few state a done condition.
  That is a real job and a separate one — roughly 60 tasks — and it is better
  done one phase ahead of the work than all at once now, when specs 005–014
  will have moved.
- **No phase-3+ task was verified against `UI_STATES.md`'s matrix.** ADR-0025
  makes the state coverage part of each UI task's definition of done, and the
  §3a/§3b component counts in `3.9` were settled by counting once. Nobody has
  re-counted since `UI_STATES.md` was corrected.
- **The `Known risks` table's "Legal posture" row still reads "Check the ToS
  of the first targets. A real input to which domains get onboarded."** True,
  but the targets are no longer build inputs, so the row describes an
  operator-time check. Left as-is deliberately: it is still the right advice,
  and rewording it risks making it sound optional.

## Handoff log

- planner — read BUILD_PLAN phases 2–6 whole, then cross-checked against
  specs 004 and 008, ADR-0008's port list, and every task-number reference in
  the repository. Ten findings; nine fixed, one filed as a decision.
- reviewer — not run. The parts worth a second reader are A1's split (does
  phase 1 now build anything with no consumer?) and A7 (is the phase-1 half
  genuinely required there, or did I pull work forward?).
- integrator — `make check` green; docs-only beyond BUILD_PLAN, which no
  target reads.
