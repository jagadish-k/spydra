# docs/1.3-targets

**Task:** BUILD_PLAN 1.3 · **Spec:** specs/002-scheduler.md §4–5,
specs/003-extraction.md §3, specs/001-domain-model.md §3 ·
**ADRs that constrain this:** 0004 (a block stops the crawler — the
`Crawl-delay` floor and honest identification), 0005 (the LLM proposes only)

`docs/` rather than `feat/`: WORKFLOW §1's table maps a build-plan task to
`feat/`, and this *is* a build-plan task, but its entire deliverable is one
documentation file and `docs/` is what makes that visible in the branch name.
A judgement call, recorded rather than silently taken.

Branched from `develop`, not from `feat/1.1-1.2-schema-and-domain`. 1.3
depends on nothing in 1.1 or 1.2, so it stays independently mergeable and
leaves the foundation branch reviewable on its own.

## Files this slice owns

- `docs/TARGETS.md` (new)
- `.tasks/docs-1.3-targets.md` (this file)

Nothing else. No code, no spec edits, no ADR.

## Acceptance (from BUILD_PLAN 1.3)

- [x] The first target domains are recorded in `docs/TARGETS.md`
- [x] Each one carries a note on its `robots.txt`
- [~] Each one carries a note on its terms — **one of three is partial and
      two are unread; the gap is recorded per domain rather than papered
      over.** See Open questions.
- [ ] ~~Two static, one JS-rendered~~ — **not met.** All three are
      JS-rendered, measured. Confirmed by the operator with that known, and
      recorded as a deviation in TARGETS.md with its two consequences.

## Sequencing decisions (planner)

- **The operator's "no required fields" instruction is recorded as a
  per-domain template policy, not as a change to spec 003.**
  `FieldRule.required` already defaults to `false`, so nothing in the schema
  or the spec has to move; the YAML templates for these three domains just
  set nothing required. Spec 003 §3's required-field routing stays
  implemented and stays tested, because `TESTING.md` §2 asks for that
  mechanism by name and the tests cover the mechanism rather than this
  configuration. Making it a global rule — the loader refusing
  `required: true` — would change spec 003's stated behaviour and wants an
  ADR; flagged in TARGETS.md, not taken here.
- **Active Motif is `auto`, not `static`.** Its categories and facets are in
  the server HTML but its product grid is not. `auto` costs one wasted cheap
  fetch when it is wrong and can be pinned from observed behaviour later
  (spec 001 §3); guessing `static` costs a silently empty extraction, which
  is the failure mode this project is built around.
- **The robots.txt notes are a record, not an enforcement mechanism**, and
  TARGETS.md says so at the top. The crawler re-fetches and honours
  `robots.txt` per run (spec 002 §5); a note here that drifts from the live
  file must lose to the live file, so the file states the date it was read.

## Open questions

- **Two of three terms-of-use documents are unread.** Rapid Electronics
  (`/terms-and-conditions`, `/terms-conditions`) and Active Motif
  (`/terms`, `/terms-of-use`) could not be retrieved. Thermo Fisher's was
  reachable only through a third-party terms tracker, whose capture carries
  inconsistent dates — and whose §2 grants access **"via an industry-standard
  web browser"** while §4 reserves "rights in and to databases". That is the
  single most consequential sentence found in this task: a crawler is not a
  browser. **Read the live Terms of Use before Thermo Fisher goes `active`.**
  The operator confirmed the targets with this gap open and on the record.
- **1.4 now depends on 1.8, which inverts the phase-1 brief.** Fixture HTML
  cannot be recorded from a JavaScript-rendered page without the render
  sidecar. 1.4 was to gate lane C; it now waits on lane B. Needs sequencing
  before lane C opens. Either capture the first fixtures by hand from a
  browser, or add one genuinely static domain — `ooznest.co.uk` was verified
  as server-rendered with titles and prices and a permissive robots.txt, and
  is the only candidate found that closes the gap.
- **`Crawl-delay: 60` on Active Motif** makes any end-to-end run against it
  hours long. It is the site's stated rate and correct to honour, but the
  phase-1 and phase-2 exit criteria should be demonstrated against one of the
  other two.
- **No `schema.org/Product` on any of the three**, so spec 003 §1's
  `structured` rung has no real fixture from the confirmed targets.

## Handoff log

- planner — robots.txt fetched and read for all three domains; terms
  attempted for all three and the outcome recorded honestly per domain;
  render mode **measured** for each by reading the server HTML rather than
  inferred. TARGETS.md written with the operator's confirmation, the
  no-required-fields policy and its consequences, and the two deviations from
  1.3 that the confirmation leaves standing.
- reviewer — not run. Docs-only, but the deviation list and the terms gap are
  the parts worth a second reader.
- integrator — nothing to gate: no code, and `make check` does not read this
  file. The claims in it are the review surface.
