# feat/1.14-yaml-loader

**Task:** BUILD_PLAN 1.14 and the phase 1 exit · **Spec:** 003 §5, 001 §1,
012 §4, TESTING.md §2 · **ADRs:** 0017, 0023, 0027, and two new ones (below)

Stacked on `feat/1.13-worker`.

## Contract

- **The loader.** `python -m spydra.load <file.yaml>` reads one YAML file and
  writes it to the `crawl` schema, then seeds a run. The file holds
  domains, each with its politeness and render settings, its templates and
  its seed URLs. Concretely, in one transaction:
  - upsert each domain by host and set it `active`;
  - insert each template as a new version, active (ADR-0006 versioning; the
    YAML is the operator's approval);
  - create a `runs` row and enqueue the seed URLs.
- **Scaffolding with a known end date** (BUILD_PLAN 1.14, deleted in 3.2).
  No schema, no validator, no inheritance. The one check it makes is the one
  it must make: **any `required: true` is refused** with a message naming
  ADR-0027, and nothing is written.
- **The template JSON is the 1.13 codec** (`extraction_to_json`, spec 013
  §2's `FieldCandidate`), so a YAML template and a phase-3 template are the
  same bytes.
- **YAML parser: `ruamel.yaml`**, safe and pure. **ADR-0035.** PyYAML, the
  obvious choice, publishes no cp315 wheel for any platform (verified on
  PyPI on 2026-10-22, PyYAML 6.0.3), so ADR-0017's gate refuses it.
  ruamel.yaml 0.19.1 ships `py3-none-any`, and its C extensions are
  optional extras.

## Exit: the phase 1 exit criterion

The criterion: the local fixture site crawled politely end to end from a
YAML file, with a static page and a JS-dependent page, both fetchers driven
by the same scheduler, and asset rows enqueued. Stopping `render` leaves
static crawling unaffected and makes `auto` record `static_fallback`.

- **The worker and the sidecar cannot see the same fixture site today.**
  `render` is alone on `egress` (ADR-0023), and the worker is on `default`.
- So a test-only `fixtures` service runs 1.4's own `server.py`. It is
  behind a compose **profile**, so `make up` never starts it, and it joins
  both networks. **ADR-0036** records this as a bounded exception to
  ADR-0023: only static test pages become reachable from inside the
  browser, and only when the profile is up.
- `make phase1-exit` starts db, render, fixtures and worker, loads
  `backend/tests/fixtures/phase1/render-up.yaml` and `render-down.yaml`, waits for the run, asserts, then
  stops `render` and repeats for the AUTO domain.

## Acceptance

- [ ] A template with `required: true` is refused with ADR-0027 in the
      message, and nothing is written.
- [ ] Loading the same file twice gives new template versions, not
      duplicates, and a new run.
- [ ] `make phase1-exit` passes:
  - the static product is extracted;
  - the rendered product (`mertens/product-rendered.html`) is extracted
    through the sidecar;
  - asset rows are enqueued and the run is `completed`;
  - with `render` stopped, the AUTO domain records `static_fallback` and the
    static domain is unaffected.
- [ ] TESTING.md §2's politeness tests pass (they exist from 1.8/1.9/1.13).
- [ ] `make check` green.

## Handoff log

- test — Added `backend/tests/test_load.py` (pure parsing plus the exit
  files run through the real chain) and
  `backend/tests/adapters/postgres/test_load_configuration.py` (Postgres
  and the CLI), 43 tests in total. Full suite: 595 passed, 2 skipped.
  `make lint-api` is clean. No production defect found. Checked by
  breaking the code on purpose, then restoring it: with `_refuse_required`
  turned into a no-op, 14 tests fail. With the transaction split into a
  commit per domain, the two atomicity tests that fail inside the database
  go red (negative `crawl_delay_ms` on the second domain, caught by the
  `configured_crawl_delay_ms_non_negative` check). With `render_mode` and
  `crawl_delay_ms` dropped from the upsert's `DO UPDATE`, the reload test
  fails. The tests for an unknown transform or a missing `selector` fail
  while parsing, before any write, so they do not exercise the transaction
  on their own. That is why the database-refusal case exists. One thing
  for the reviewer: YAML 1.2 reads `required: yes`, `on`, `1` and
  `"true"` as non-booleans. The loader accepts all four silently, and the
  codec then drops the key. This is outside the literal acceptance
  ("`required: true`"), but it is the silent-belief case that ADR-0027
  argues against. No test was written for it. Also, `runs.domain_ids`
  comes from domains that have seeds, so a domain that has templates but
  no seeds is set active but left out of the run. That is not tested
  either. Next: `spydra-reviewer`.

- backend (after test): two gaps the test-writer found are closed, and
  that **supersedes the test line above**. Any `required` value except a
  literal `false` is refused (`yes`, `on`, `1`, `"true"` too), and the run's
  `domain_ids` covers every domain in the file, seeded or not.
- reviewer (fresh context; did not write the code): 3 blocking findings,
  7 non-blocking. It ran `make phase1-exit` (green) and probed concurrent
  loads (safe: the conflicting row lock serialises them).
  1. **Blocking, fixed.** A reload reset a `paused` domain to `active` and
     wiped its 429 backoff: a retry through a block.
     - Existing domains now go through the lifecycle. A candidate
       (`discovered`, `awaiting_approval`) walks PROPOSE/APPROVE to
       `active`.
     - `paused`, `broken` and `archived` refuse the whole load, naming the
       state.
     - The live delay is only ever raised to the new floor. The test that
       blessed the old behaviour is replaced by refusal, approval and
       backoff-kept tests.
  2. **Blocking, fixed.** A seed on another host would have been crawled
     under the wrong domain's robots and politeness. Such a seed is refused.
  3. **Blocking, fixed.** The Linux override was an undocumented second
     hole in ADR-0023: a page in the browser can reach the sidecar's API at
     the bridge address. The exit script also left it in place afterwards.
     - It is now recorded in ADR-0036 as a second bounded exception, with
       its cost stated.
     - The script restores `render` from `compose.yaml` alone, and only if
       it was running before.
  4. **Fixed.** `many: no` and `respect_robots: no` used to read as true.
     Boolean keys must now be YAML booleans.
  5. **Left as is.** Misspelt keys are still ignored: BUILD_PLAN 1.14 says
     no validator.
  6. **Fixed in part.** The checker now fails fast on a `failed` or
     `stopped` run. "Politely" is proven by TESTING.md §2's tests inside
     `make check`, which runs first in CI.
  7. **Fixed.** ADR-0036 now names all four fixture hostnames.
  8. **Fixed.** Stale docs: `server.py`, the task file's file names, and the
     handoff line above.
  9. **Left as is.** A field cannot be named `required`. The walk is broad
     on purpose.
  10. **No change.** `by_strategy` reports a `static_fallback` page that
      extracted nothing as `none`, which is the rung that produced fields.
      That is correct by its own definition.

## Open questions — for the human

1. The `fixtures` profile service on `egress` (ADR-0036). The alternative,
   running the whole exit inside the render container, cannot exercise the
   worker.
2. **ADR-0023 has no Linux deployment answer.** Its worker-to-sidecar path
   (a host-loopback publish reached through `host.docker.internal`) works
   only on Docker Desktop. On Linux Docker Engine, which is what CI and any
   Linux host run, the worker cannot reach the sidecar at all. The exit uses
   a run-scoped override (ADR-0036). A deployment needs a real decision.
3. **A file cannot resume a paused domain, by design.** There is no resume
   command until the API (phase 2). Until then, an operator resumes with
   SQL. That is acceptable for a scaffold, but worth knowing.
