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
  `backend/tests/fixtures/phase1.yaml`, waits for the run, asserts, then
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

## Open questions — for the human

1. The `fixtures` profile service on `egress` (ADR-0036). The alternative,
   running the whole exit inside the render container, cannot exercise the
   worker.
