# fix/2.0-phase1-decisions

**Task:** three phase-1 open questions the human has decided, before phase 2
starts. No BUILD_PLAN number of its own; the tick is a note under phase 1's
exit. **Specs:** 003 §3, 002 §5, 009 §1/§5, 010, 012 §3/§6 · **ADRs that
constrain this:** 0016, 0023, 0027, 0030, 0036, and two new ones (below).

Branches from `develop` (all of phase 1 merged, #10–#20).

## The three decisions (the human's direction; the shapes are ours)

### D1. An image-only SEO stub over a broken template counts as empty

`fix-1.11-review-findings` open question 12.

**Today (to reproduce before fixing):** a page with an approved template that
comes back empty, plus a JSON-LD `Product` carrying only `image`, gets the
stub's `{images: [...]}` from the chain. `empty_extraction` is `false`, so no
`unknown_pages` row and no count toward ADR-0030's threshold. A redesign on
such a domain writes NULL-title rows and never trips `broken`.

**Shape chosen: change the predicate, not a second verdict.**

- `empty_extraction(status, fields) ⇔ status == 200 and not
is_substantive(fields)`.
- **Why the predicate and not a writer-side verdict.** ADR-0027's
  constraint is "one predicate, three callers". 1.13 already broke it: the
  AUTO second chance (caller 1) uses `not is_substantive`, while the inbox
  reason and the threshold (callers 2, 3) use `empty_extraction`. That is two
  definitions of "nothing usable" in production today. A second verdict the
  writer computes would make it three: the observation column would say
  `empty_extraction = false` on a row the inbox files as `empty_extraction`,
  and the threshold query (which reads the column) would need a new column or
  its own re-derivation. Redefining the predicate makes all three callers
  agree again, which is what ADR-0027 asked for.
- **"A template was consulted" is not in the predicate**, and does not need
  to be. A page with no template is still `no_template` (outranks), and is
  still outside the threshold (ADR-0027 §3). The chain runs every rung until
  one is substantive, so on a page with a template the selector was always
  consulted when the result is not substantive.
- **The images keep flowing.** The chain stops using `empty_extraction` to
  decide what to keep. It skips a rung only when nothing resolved at all, and
  keeps the first non-blank, non-substantive result as its fallback, as
  today. The writer enqueues `asset_urls(result.fields)` as today, so the
  stub's images still reach `asset_queue`.
- **History is not rewritten** (rule 13). Rows written before this change
  carry `empty_extraction = false` for an image-only page. ADR-0030's prior
  ("an earlier observation whose extraction was non-empty") is therefore read
  as **`prior.content_hash IS NOT NULL`**: `content_hash` is `NULL` exactly
  when the extraction was not substantive (1.11 B3), so it gives the new
  answer for old rows without an `UPDATE`. Side effect, intended: a prior
  non-200 row with nothing in it no longer counts as "once worked" (today
  `NOT empty_extraction` is true for every non-200 row).
- **No import cycle:** `hashing` imports `validation.is_empty`; `validation`
  cannot import `hashing`. Resolve by moving the predicate's dependency, not
  by a local import (implementer's call; record it).
- AUTO (`scheduler/crawl.py`) goes back to calling `empty_extraction`, so
  caller 1 is literally the same function again.
- **ADR-0037**, amending ADR-0027 (and touching ADR-0030's prior), records
  this, including the argument against the alternative.

**Cost, to state in the ADR:** a template whose only fields are asset URLs (or
URL-valued data) now yields `empty_extraction` on every page. No template in
the repo does this; the authoring pipeline (phase 3) should warn on it.

### D2. Worker → sidecar works on Linux Docker Engine and Docker Desktop

`feat-1.14-yaml-loader` open question 2; ADR-0036's Linux exception.

**Today (to reproduce before fixing):** `RENDER_BASE_URL =
http://host.docker.internal:3001`, `render` published on `127.0.0.1` only. On
Linux the worker's connection is refused. `docker/compose.linux.yaml` adds a
publish on the docker0 gateway for the exit run, and while it is up a page in
the browser can reach the sidecar's own API.

**Shape chosen: a dedicated two-member internal network, plus a sidecar that
refuses browser-shaped requests.**

- New network **`render-link`**, `internal: true`, members `worker` and
  `render` only. `RENDER_BASE_URL=http://render:3001` for the worker. Same
  compose file on both platforms; no per-OS override, no host hop.
- `render` stays on `egress` (its only way out) and joins `render-link`. It
  is still on no network with `db`, `api`, `bff`, `edge`, `web`. Through
  `render-link` it can resolve `worker`, which listens on nothing (measure).
- **The sidecar refuses requests whose source is the browser.** Chromium
  attaches headers a page cannot remove or forge (`Origin` on every POST and
  every CORS request, `Sec-Fetch-*` to trustworthy origins). `RenderService
Fetcher` (httpx) sends none of them. So: any request carrying `Origin` or a
  `Sec-Fetch-*` header gets `403`, and `POST /render` requires
  `content-type: application/json` (a cross-origin page fetch with that type
  is preflighted, and the sidecar answers no preflight). Checked before the
  body is read.
- Rejected, for the ADR:
  - **source-address check** (refuse loopback/own IPs): the acceptance suite
    drives the sidecar from inside its own container, so it would need an
    opt-out switch, and a guard with an off switch is the gate that cannot
    fail;
  - **per-OS override** (loopback on macOS, gateway on Linux): keeps
    ADR-0036's measured hole on Linux in normal `make up`;
  - **`worker` joins `egress`**: the browser could then resolve and reach
    every service the worker can't hide (it listens on nothing, but `egress`
    is also where `fixtures` lives).
- `render` keeps `127.0.0.1:3001` as a **dev inspection port** like the
  others (the audit script and DEVELOPMENT.md use it). It is no longer the
  fetch path. `worker` keeps `extra_hosts` (llama-server, ADR-0009).
- **The api has no path to the sidecar** after this, and needs none today
  (grep: nothing under `spydra/api` calls it). Spec 010's api `/healthz`
  `render` field and spec 014's `/inspect` will need one in phase 3. Raised.
- **ADR-0038** supersedes ADR-0023 §Decision 1–2/4 (the host-loopback path);
  ADR-0023 §3 (loopback-only inspection ports) stands. ADR-0036 loses its
  Linux exception. `docker/compose.linux.yaml` is deleted;
  `scripts/phase1-exit.sh`, `compose.yaml`, DEVELOPMENT.md, spec 010 and
  spec 012 §3 updated.

**Measurement required (Linux, this container), from inside `render`:**
`db:5432`, `api:8000`, `bff:3000`, `edge:8080`, `web:5173` do not resolve;
the egress gateway's published ports (5432, 8000, 3000, 8080, 5173, 3001)
refuse; `worker`'s address has no listening port; a page loaded in the browser
that POSTs to `http://render:3001/render` and `http://127.0.0.1:3001/render`
does not get a render. The macOS half cannot be measured here (no Docker
Desktop in reach); raised.

### D3. Spec 009 gives way to spec 002 §5

`feat-1.13-worker` open question 5.

- `robots_override` stays a `warning`, on every page it takes effect.
- Spec 009 §5's line budget gets an explicit carve-out: **operator
  overrides** (today only `robots_override`) are not counted, because they are
  the operator's own instruction, attributed per page on purpose.
- Edit spec 009 §1/§5. Not an ADR: it reconciles two specs on a logging
  budget and changes no structure.
- The 1,000-page budget test asserts the carve-out: on a
  `respect_robots = false` domain, exactly one `robots_override` per page,
  and every **other** line counts against `< 100`. So any other per-page
  `info`/`warning`/`error` line fails it.

## Files this slice owns

- backend/spydra/extraction/{validation,chain,hashing}.py (+ a new module if
  the cycle needs one), backend/spydra/extraction/**init**.py
- backend/spydra/observations/writer.py (docstrings at least)
- backend/spydra/adapters/postgres/observations.py (`_HEALTH` prior)
- backend/spydra/scheduler/crawl.py (AUTO back on the predicate)
- backend/spydra/adapters/http/{auto_fetcher,render_service_fetcher}.py,
  backend/spydra/worker.py (docstrings)
- render/src/index.js (+ a small module for the guard)
- compose.yaml, docker/compose.linux.yaml (deleted), scripts/phase1-exit.sh,
  .github/workflows/check.yml (comment)
- docs/adr/0037-_.md, docs/adr/0038-_.md, docs/adr/{0023,0027,0030,0036}
  (status lines), docs/adr/README.md
- docs/specs/{003,009,010,012}.md, docs/DEVELOPMENT.md, docs/TESTING.md §2 if
  it names the predicate
- backend/tests/**, render/tests/** (test-writer)

## Acceptance

D1

- [ ] Reproduced first: stub + broken template → `empty_extraction = false`,
      no inbox row (throwaway, not committed).
- [ ] Stub + template that comes back empty → the row is `empty_extraction`,
      an `unknown_pages(empty_extraction)` row opens, and the stub's images
      are in `asset_queue`.
- [ ] On a domain whose pages once extracted, enough such pages trip `BREAK`
      past 20%; on a first run, `NEVER_MATCHED` (ADR-0030 unchanged).
- [ ] An old-style row (`empty_extraction = false`, `content_hash IS NULL`)
      is **not** a prior: a later empty page is not a regression.
- [ ] Stub alone (no template) → `no_template`, images enqueued.
- [ ] Stub + working template → template's fields, not empty (1.11 B3 kept).
- [ ] AUTO's second chance fires exactly when `empty_extraction` does.
- [ ] `test_a_page_whose_only_field_is_an_asset_url_is_not_empty` changed
      deliberately (renamed, inverted, docstring says why), not deleted.

D2

- [ ] Reproduced first: on `develop`'s compose, the worker cannot reach
      `host.docker.internal:3001` on Linux.
- [ ] Normal `make up` topology: the worker renders a page through
      `http://render:3001` on Linux, with no override file.
- [ ] The measurements listed under D2, recorded in the handoff log.
- [ ] Sidecar: a request with `Origin` or any `Sec-Fetch-*` → 403; a
      `POST /render` without `content-type: application/json` → 415 (or
      403; record which); a page whose script POSTs to the sidecar does not
      cause a second render. In the render acceptance suite.
- [ ] `make phase1-exit` green on Linux with no override file; nothing in
      `compose.yaml` binds `0.0.0.0`.

D3

- [ ] Spec 009 §5 carve-out written; spec 002 §5 unchanged.
- [ ] The 1,000-page test runs `respect_robots = false`, asserts 1,000
      `robots_override` lines and `< 100` others; it goes red when any other
      per-page `info`/`warning` line is added (mutation).

All

- [ ] `make check` green; `make phase1-exit` green.
- [ ] Mutation run on every guard, scratchpad runner: "N chosen, M red",
      survivors named.

## Handoff log

- planner (main session): read AGENTS.md, WORKFLOW.md, BUILD_PLAN phase 2,
  the four latest task files, ADRs 0023/0027/0030/0036, specs 002/003/009/
  010/012, the chain, writer, health query and render server. Shapes above.
  Baseline `make check` on `develop` in this container: 611 passed, 2
  skipped; `test-render` red only on the known 20 MB/30 s timeout.
- backend + ops (main session; the implementer role):
  - **D1 reproduced** through the real chain (scratchpad script): stub +
    vantage template with every selector broken → `structured
{images:[…]}`, `empty_extraction False`, reason `None`.
  - **D1 built as planned.** `is_empty` moved to `extraction/emptiness.py`
    (with `is_blank`), which breaks the `validation ↔ hashing` cycle;
    `validation` no longer re-exports it, the package does.
    `empty_extraction = 200 and not is_substantive`. The chain skips a rung
    only when `http_status == 200 and is_blank(fields)`: **deviation** —
    skipping blanks on a 404 too changed the 404's `strategy` from `selector`
    to `None` and broke 1.13's "every page line names its strategy" test.
    That is a behaviour change nobody asked for, so the 200 condition stays
    (it was implicit in the old predicate). AUTO calls `empty_extraction`.
    `_HEALTH`'s prior is `content_hash IS NOT NULL`.
  - **D1 left for the test-writer:** 15 existing tests now fail. Most seed a
    "non-empty prior" with `seed_observation(empty=False)` and no
    `content_hash`, a row the writer cannot produce since 1.11. The helper
    needs a hash when `empty=False`. Plus the two stub tests to invert.
  - **D2 reproduced** on `develop`'s compose: worker →
    `host.docker.internal:3001/healthz` = `ConnectError [Errno 111]`.
  - **D2 built:** `render-link` (internal), worker env `RENDER_BASE_URL=
http://render:3001` via a YAML merge so the api does not carry a name it
    cannot resolve, `render/src/guard.js`. Node's `fetch` sends
    `sec-fetch-mode: cors` (measured), so the guard keys on `Origin`,
    `Sec-Fetch-Site/-Dest/-User` and not on `-Mode`.
    `docker/compose.linux.yaml` deleted; `phase1-exit.sh` has one compose
    file and restores render as it found it.
  - **D2 measured** (full stack up, from inside `render`): table in ADR-0038.
    A page's POSTs to the sidecar caused 0 renders; with the guard removed
    (copy of the sidecar on :3002) the same page caused 5. `make
phase1-exit` green on Linux with no override.
  - **D3:** spec 009 §1 carve-out and §5 acceptance text. Test is the
    test-writer's.
  - ADR-0037, ADR-0038; status lines on 0023/0027/0030/0036; specs 001,
    003, 009, 010, 012; DEVELOPMENT.md.
- test (spydra-test): written from the Acceptance list, ADR-0037/0038 and
  spec 009 §1/§5. No production code touched.
  - **Before:** 15 backend failures (13 in `test_observations.py`, 1 in
    `test_chain.py`, plus the asset-URL test). **After:** backend 639
    passed, 2 skipped, 0 failed; render 55/55 (the 20 MB A6 case passed
    this run); `make lint-api` clean.
  - **Seed helper, deliberately:** `observation_seed.seed_observation`'s
    `content_hash` now follows `empty` (a fixed digest when `empty=False`),
    because a non-empty row with no hash is a row the writer cannot produce
    since 1.11. `content_hash=None, empty=False` is kept as the explicit way
    to seed the legacy shape. That alone fixed 13 of the 15.
  - **Changed on purpose, not deleted:**
    `test_a_page_whose_only_field_is_an_asset_url_is_not_empty` →
    `..._is_an_empty_extraction`; `test_an_image_only_jsonld_stub_alone_
still_yields_its_images` → `..._yields_its_images_as_an_empty_extraction`;
    `test_an_image_only_stub_has_no_hash_and_is_never_unchanged` now asserts
    `empty_extraction = true`. Docstrings cite ADR-0037.
  - **New fixture:** `vantage-abrasives/product-image-stub-redesigned.html`
    (the stub's JSON-LD over renamed classes), hand-written, in the README.
  - **D1 tests:** `test_validation.py` (predicate table incl. image-only,
    hollow price, non-200; package export is the same function);
    `test_chain.py` (stub over redesign → stub kept + empty; working template
    behind stub → not empty; a 404 still names `selector`, the same page at
    200 names none); `test_observations.py` (stub over redesign → row empty,
    inbox `empty_extraction`, share image in `asset_queue`; 2/5 with priors →
    `BREAK`/`broken`; first run → `NEVER_MATCHED`/`awaiting_approval`; prior
    table: legacy `false`/NULL-hash row and blank 404 row are not priors, a
    hashed row is; stub with no template → `no_template`, image queued,
    outside the threshold; B3 test now also asserts not empty, no inbox);
    `test_page_crawler.py` (AUTO renders iff `empty_extraction`, six bodies
    incl. gallery-only).
  - **D2 tests:** `render/tests/guard.test.js` (each header 403 on both
    routes, `sec-fetch-mode` alone served, 415 table) and acceptance block
    "ADR-0038": raw `node:http` requests per header → 403 and no render;
    415 for none/text/form; refusal before body read (100 KB → 403/415, not
    413); Node `fetch` healthz → 200; a worker-shaped control render hits
    the marker once; a page served by the test, rendered by the sidecar,
    POSTs to the sidecar on loopback AND on the container's own address
    (stand-in for `render:3001`) five scripted ways plus a text/plain form,
    with decoys as the control (6 POSTs each, every one with `Origin`) → 0
    marker hits, `pages_since_restart` +1. DNS guard now lists
    api/db/bff/edge/web; `worker` excluded by design, with the reason.
  - **D3 test:** the 1,000-page test runs `respect_robots = false`, asserts
    exactly 1,000 `robots_override` lines (warning, this run, this host) and
    < 100 others; the carve-out set is named in the test.
  - **Mutation (scratchpad runner, code restored with `git checkout`,
    `git diff -- backend/spydra render/src` empty after): 16 chosen, 16
    red, no survivors.** D1: predicate reverted; prior read from
    `NOT empty_extraction`; AUTO on blank-ness; chain skips blanks on every
    status; chain drops the fallback. D3: a per-page `info` line; a
    per-page `warning` line; override logged once per run. D2: `refusal()`
    null; content-type check dropped; each of the four headers dropped;
    `sec-fetch-mode` added; guard only on `/render`. Predicate revert alone
    turns 14 tests red across the four D1 files.
  - **Finding (not a behaviour defect today; a false safety claim):** the
    `application/json` barrier does **not** hold on its own. The sidecar
    routes every request through `context.route('**/*')`, and with Playwright
    interception on, a page's CORS `application/json` POST reached `/render`
    with **no OPTIONS preflight** (measured: header list emptied, content-type
    check kept → the page caused **2 renders**, sidecar log showed the two
    JSON POSTs and no OPTIONS). `guard.js`'s "Either barrier alone would
    hold" and ADR-0038's "cannot reach it with a preflighted one either" are
    wrong for this sidecar. And on the `render:3001` path (plain http,
    non-loopback, so not a trustworthy origin) Chromium sends no
    `Sec-Fetch-*`: **`Origin` is the only thing refusing those requests**
    (measured: dropping `origin` alone → the page renders). Reviewer: the
    ADR text and the comment need correcting; the guard as written holds.
  - **Observation:** `robots_override` carries `host` and `run_id` but no
    `url`, so spec 009 §1's "each request should be attributable" is per
    host per run, not per request. Left as is; raise if it matters.

## Open questions — for the human

Carried: `fix-1.11-review-findings` 1–11 and 13; `feat-1.13-worker` 1–4 and
6–8 (1 robots outside the gate, 2 no asset pool — not relitigated);
`feat-1.14-yaml-loader` 1 and 3. Closed here: 1.11 q12 (D1), 1.13 q5 (D3),
1.14 q2 (D2).

New:

1. **The api has no route to the sidecar.** Spec 010's api `/healthz`
   reports `render`, and spec 014's `/inspect` renders through it; neither is
   built. Putting `api` on `render-link` gives the browser a route to
   `api:8000`. Phase 3 needs a decision (the worker serves inspect through the
   queue, or a second guarded link).
2. **macOS is unmeasured.** Docker Desktop resolves `host.docker.internal` in
   every container, `render` included, and forwards it to the host's
   loopback, where `db`, `api`, `bff`, `edge` and `web` publish. ADR-0023
   claimed loopback binding stops that; on Docker Desktop that claim is
   doubtful, and it is unchanged by this slice. Needs one measurement on the
   Mac (from inside `render`: `host.docker.internal:5432/8000`).
