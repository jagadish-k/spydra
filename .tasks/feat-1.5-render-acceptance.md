# feat/1.5-render-acceptance

**Task:** BUILD_PLAN `1.5` · **Spec:** `specs/012-render-sidecar.md` §1–3, §6
**ADRs that constrain this:** 0016 (render is a sidecar), 0017 (image↔package
pin), 0022 (agent team), 0023 (render is reached through the host, not a
shared network), 0028 (no mocking library — but see "What does not bind" below)

**Goal.** Six of spec 012 §6's ten acceptance criteria, exercised through
`POST /render` against `1.4`'s fixture site, behind `make test-render`. The
service shipped in phase 0 and its pure helpers (`limits`, `validate`,
`context-queue`) are unit-tested; **its HTTP contract is not tested at all.**
`1.7` (`RenderServiceFetcher`) depends on this.

---

## Measured state before any code (do not re-derive these)

Four facts were established by running commands, not by reading. Each one
changes the shape of the slice.

1. **The gate for this task cannot fail.** `make test-render` is
   `compose run --rm --no-deps render npm test`, and `compose.yaml` gives
   `render` **no bind mount** — `docker/render.Dockerfile` does
   `COPY render/tests tests`, so the suite runs the _image's_ copy.
   Measurement: a file `render/tests/zz-gate-probe.test.js` containing an
   unconditional `throw` was written on the host; `make test-render` reported
   `17 pass, 0 fail`, exit 0, and never saw it. Every test written for `1.5`
   would be invisible until someone rebuilt the image by hand. This is the
   "a gate that cannot fail is worse than no gate" failure, in the one place
   that would have hidden the whole task.
2. **`1.4`'s fixtures are not reachable from the sidecar.**
   `spydra-render:latest` contains `/app/{src,tests,node_modules,package.json}`
   and no `backend/`. From inside the render container, `db`, `api` and `bff`
   all fail DNS resolution — ADR-0023's isolation is real and intact, which is
   also exactly why the fixture server running in the `api` container cannot
   be reached. The image **does** carry `python3 3.12`, so `1.4`'s stdlib
   `server.py` can run on the render container's own loopback.
3. **Two §6 criteria have no fixture, and one must never have a committed
   one.** `1.4` shipped 7 pages / 3 robots variants. The six criteria also
   need a page that stalls (to hold three contexts past the 5 s queue
   window), an image-heavy page, an `alert()` page, and a ~20 MB response.
   The oversized one **cannot be a file** — pre-commit rejects anything over
   2 MB — so the fixture server synthesizes it per request.
4. **Two constants are not observable as written.**
   `index.js` does `new ContextQueue(CONTEXTS_MAX, 5000)` with the window
   hardcoded, and `RECYCLE_AFTER_PAGES` defaults to 500 with `compose.yaml`
   pinning 500. The 503 criterion and the recycle criterion cannot be proven
   without env overrides. The overrides must not be able to weaken the
   spec'd defaults — 5 s and 500 stay the defaults, and a test that forgets
   to set the env sees spec behaviour, not test behaviour.

## Decisions taken (operator, before planning)

- **The fixture site runs on the render container's own loopback.**
  `compose.yaml` bind-mounts `./render:/app` (with a `render_modules` named
  volume, as `bff` and `web` already do) and
  `./backend/tests/fixtures:/fixtures:ro`; the Node suite spawns
  `python3 -m server` from the mount and talks to `127.0.0.1`.
  `render` stays **alone on `egress`** — ADR-0023 is untouched and no second
  host becomes resolvable from the browser.
  _Rejected:_ a `fixture-site` service on `egress` (makes a name resolve from
  render, needs an ADR-0023 note, and still needs the bind mount anyway); a
  Node static server inside `render/tests/` (a second implementation of
  `1.4`'s route table — the drift the single-source JSON-LD twins exist to
  prevent).
- **The gate fix ships in this branch,** declared here and called out in the
  PR body. It is ops work in a `feat/` slice, which bends WORKFLOW §1's one
  task per branch; `1.5` is unprovable without it, so splitting it would mean
  a `feat/1.5` that cannot be shown to work until a second PR lands.

## What does not bind here

- **ADR-0028 (`httpx2` + `MockTransport`) does not apply to this suite.** It
  governs the Python suite's HTTP mocking. This is a Node suite whose entire
  point is a real browser making real requests; there is nothing to mock.
- **"No network" means no public internet, not no sockets.** TESTING.md §1
  permits loopback fixture serving explicitly, and BUILD_PLAN `1.4`'s "done
  when" names the sidecar suite as one of its two consumers.
- **Politeness is not this service's concern** (spec 012 §1). No politeness
  assertion belongs in this suite.
- **"Never a mocked clock" does bind.** `block_resources` and the recycle
  criterion are settled on observed elapsed time and observed
  `pages_since_restart`, not on injected timers. `ContextQueue`'s injectable
  timers stay available to the _unit_ suite and are not used here.

## Files this slice owns

```
compose.yaml                                  (render: binds + env knobs)
render/src/index.js                           (RENDER_QUEUE_WAIT_MS, RENDER_PORT)
render/tests/acceptance.test.js               (NEW — the six criteria)
render/tests/helpers/service.js               (NEW — boot service + fixtures)
backend/tests/fixtures/server.py              (routes + generated shapes)
backend/tests/fixtures/pages/mertens/product-dialog.html      (NEW)
backend/tests/fixtures/pages/vantage-abrasives/product-images.html (NEW)
backend/tests/fixtures/README.md              (the new shapes, and why)
backend/tests/test_fixture_site.py            (guards for the new shapes)
docs/TESTING.md                               (§1, §4 — the fixture tree)
docs/BUILD_PLAN.md                            (tick 1.5; 1.7 gains a criterion)
```

Four corrections to the plan above, recorded rather than quietly dropped:

- **`Makefile` is NOT changed.** The plan expected to; `compose run` already
  mounts the service's declared volumes, so the gate fix is entirely in
  `compose.yaml`. Raised by review — the ops handoff claimed a file it had
  not touched.
- **`docker/render.Dockerfile` is NOT changed.** Its `COPY render/tests`
  stays so the shipped image is self-contained; the binds only win in dev.
- **`product-slow.html` was never created.** `/slow/<ms>` replaced it: a
  stall is a property of the server, not of bytes on disk.
- **`backend/tests/test_fixture_site.py` and `docs/TESTING.md` were not in
  the original plan** and are now declared. The first is `1.4`'s own
  fixture-guard suite, extended by `1.4`'s own reasoning; the second had
  drifted — its §4 tree enumerates fixtures file-by-file and §1 called them
  all "committed".

**Not owned, do not touch:** anything under `backend/spydra/`, `bff/`,
`frontend/`, `docs/SCREENS.md`, `docs/UI_STATES.md`, `docs/COMPONENTS.md`,
the Figma file. No disjoint-file-set parallelism is available — Phase 1 is
linear and `1.6` touches `backend/spydra/adapters/http/`.

## Acceptance (from spec 012 §6 — the six a real browser can prove)

- [x] **A1 — JS-dependent content.** `/katalog/stirnlochschluessel-30-80`
      rendered contains `produkt__preis`; the **raw** response for the same
      URL does not. Both halves, or the test passes against a page that was
      never dynamic.
- [x] **A2 — the fourth request 503s.** Three renders held in flight on the
      slow fixture, a fourth queues for the window and returns **503**. Also
      assert `GET /healthz` reports `contexts_in_use: 3` throughout — the
      criterion is "rather than opening a fourth context", and a 503 alone
      does not prove a fourth context was never opened.
- [x] **A3 — `block_resources` measurably reduces render time.** The
      image-heavy fixture rendered with `[]` and with
      `["image","font","media"]`; compare observed `timing_ms.total`.
      Threshold stated in the test and justified, not a bare `<`.
- [x] **A4 — `alert()` does not hang.** The dialog fixture returns 200 well
      inside its own `timeout_ms`, and the response body is the
      post-dialog DOM.
- [x] **A5 — recycle without dropping an in-flight render.** With
      `RECYCLE_AFTER_PAGES` low: drive past the threshold, start a slow
      render, force a recycle with a concurrent request, and assert the slow
      render still returns 200 and `pages_since_restart` reset.
- [x] **A6 — oversized response truncated and flagged.** The synthesized
      ~20 MB page returns 200 with `truncated: true` and an `html` whose
      byte length is exactly at `MAX_HTML_BYTES`.

**Every one of the six is mutation-tested.** Break the guard in `src/`,
prove that test and only that test goes red, restore. Record each in the
handoff log. A criterion whose test stays green with its guard broken is not
done.

## The four §6 criteria this task does not cover

Required by `1.5`'s "done when". Listed with the phase that will cover each.

| §6 criterion                                                                                                                     | Phase / task                                 | Why not here                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| With `render` stopped: `static` crawls, `auto` falls back and records `static_fallback`, `rendered` stalls honestly              | **`1.7`**, and again at the **Phase 1 exit** | It is a property of `RenderServiceFetcher` and the scheduler, asserted from the Python side. Nothing in this suite can observe it — the sidecar cannot test its own absence.                                                                                                                                                                                                                                                                                                                                 |
| `/inspect` and `/render` share the context cap: three renders in flight make an `/inspect` call queue, not open a fourth context | **`6.1`**                                    | `/inspect` does not exist yet; spec 012 §1 defers its contract to spec 014 §2. `6.1` already carries "sharing the existing context cap and the egress-only network". `A2` proves the cap itself, so `6.1` only has to prove `/inspect` enters the same queue.                                                                                                                                                                                                                                                |
| The Python image contains no `playwright` package and no browser                                                                 | **`1.7`** (recommended)                      | Needs no browser, so it is outside `1.5`'s stated scope ("the six a real browser can prove"), and it is a Python-side assertion about the `api`/`worker` images. `1.7` is where spec 012 §1's claim that the Python side has "no browser dependency at all" is first load-bearing. **It is currently asserted nowhere** — `docker/api.Dockerfile` and `docker/worker.Dockerfile` only say so in a comment, and `backend/tests/test_import_contracts.py` does not check it. Cheap to add; see Open questions. |
| A page fetching `http://api:8000/…` cannot reach it (network isolation)                                                          | **no task owns it — raised below**           | Needs the full stack up. `make test-render` runs `--no-deps`, so `api` is not running and a page failing to reach a service that was never started proves nothing.                                                                                                                                                                                                                                                                                                                                           |

## Mutation matrix

Every criterion's guard broken on purpose, the suite run, the guard restored.
Run with `node --test --test-reporter=tap tests/acceptance.test.js` inside
the render container so the red set is machine-readable.

| Criterion | Mutation applied to `render/src/`                                                                      | Result                                             |
| --------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------- |
| A1        | `truncateHtml(await page.content())` → `response.text()` (stop using the browser's DOM)                | red — **after a fix; see finding M1**              |
| A2        | `ContextQueue.acquire`'s `this._active < this.max` → always true                                       | red, and only A2                                   |
| A3        | the `route.abort()` branch disabled, so `block_resources` is ignored                                   | red, and only A3                                   |
| A4        | `page.on('dialog', …)` → a listener that dismisses nothing                                             | red, and only A4 — **after a fix; see finding M2** |
| A5        | `if (due) this._retireActive()` disabled, so the browser never recycles                                | red, and only A5                                   |
| A5        | `_retireActive()` closes the old browser unconditionally, killing a live render — **the drain itself** | red — **after a fix; see finding M3**              |
| A6        | `truncateHtml` returns `{ truncated: false }` before it measures                                       | red, and only A6                                   |

A1's mutation also reds A6, which is expected rather than noise: reading a
20 MB navigation body instead of the DOM changes the oversized case too.

**Three of the six were green against a broken service on the first pass.**
That is the whole argument for the step, and it is worth stating plainly:
without it, this slice would have shipped a `1.5` that proved three of its
six criteria and looked identical in CI.

### M1 — A1 was weak, and the mutation is what found it

The first version of A1 asserted `/produkt__preis/` against the rendered
HTML. **It stayed green with the browser's DOM taken out of the response
entirely.** `mertens/product-rendered.html` writes its product from a
JavaScript _string literal_, so `produkt__preis` is present in the page
**source** as well as in the rendered DOM — the assertion was satisfied by
the script that had never run.

The fix makes both halves symmetric: raw and rendered are each compared with
`<script>` elements stripped, and the rendered side asserts on
`class="produkt__preis"` as an attribute rather than the bare token. A1 then
goes red under the mutation.

`backend/tests/test_fixture_site.py::test_the_rendered_page_is_empty_before_javascript_runs`
had already got this right for the raw half — the trap is only visible on
the rendered half, which is new here.

### M2 — the dialog guard in `src/` is not what makes A4 pass

Deleting `page.on('dialog', (d) => d.dismiss())` outright leaves A4 **green**:
Playwright auto-dismisses dialogs when _no_ listener is attached. The line is
therefore belt-and-braces, and the mutation that actually exercises the
criterion is a listener that dismisses nothing — which is also the real
regression risk, since a future `page.on('dialog', …)` added for logging
would silently start hanging every page that opens one. Recorded here because
"the guard is redundant" and "the guard is untested" look identical from a
green suite, and they are not the same thing.

### M3 — A5 never put a render in flight across the recycle

The first version did two warm-up renders to reach `RECYCLE_AFTER_PAGES=2`,
then started a slow render and fired a second to "force" the recycle. Traced
against `render/src/index.js`, `acquire()` retires a due browser **before**
taking a reference — so with the threshold already reached it is the **slow
render itself** that trips the recycle. `old.refs === 0` at that instant, so
the old browser closes immediately and the slow render runs on the fresh one.
Nothing was ever in flight across a restart, and the deferred-close branch in
`release()` — which _is_ the no-dropped-render guarantee — was never reached.

Confirmed by mutation: with `_retireActive()` closing the old browser
unconditionally (a recycle that kills a live render, exactly what the
criterion forbids), **A5 stayed green**. The test's own comment asserted the
opposite of what the code did.

The fix is the ordering — reach the threshold only _after_ the slow render
holds a reference, and let a later request be the one that trips it. The
discriminating assertion is then `drained.status === 200`: a broken drain
leaves that render talking to a dead browser. Both A5 mutations now red.

Found by review, not by the author, and WORKFLOW §3's starved-context review
is why it was findable — the test and its comment agreed with each other, and
only the code disagreed.

## Handoff log

- **planner** — contract above. Four facts measured rather than assumed
  (see "Measured state"); the first of them means the gate for this task
  could not have failed, so the ops change is a precondition, not polish.
  Both operator decisions recorded with their rejected alternatives. Owned
  file list is deliberately wide because the slice spans `render/`,
  `backend/tests/fixtures/` and compose — all three are needed for one
  criterion to be provable.
- **ops** — `compose.yaml` now binds `./render:/app` with a `render_modules`
  named volume and `./backend/tests/fixtures:/fixtures:ro`; `render` is still
  alone on `egress`. Three env knobs added, each defaulting to the spec value
  so an unset or junk env cannot weaken it: `RENDER_QUEUE_WAIT_MS` (5000),
  `RECYCLE_AFTER_PAGES` (500, previously pinned in compose), `RENDER_PORT`
  (3001 — the suite needs two instances with different settings, and 3001 was
  hardcoded). `FIXTURE_HOST` added to `1.4`'s server so the sidecar's suite
  binds loopback rather than `0.0.0.0`: a fixture site on the egress network
  would be a name the browser can resolve, which is what ADR-0023 denies.
  **Gate proven in both directions**: a planted failing test makes
  `make test-render` exit 2, and a clean tree exits 0. Before this change the
  same planted test was invisible and the target exited 0.
- **test (fixtures)** — four shapes added. Two are files
  (`product-dialog.html`, `product-images.html`); two are generated per
  request by `1.4`'s server (`/slow/<ms>`, `/oversized/<mb>`, plus
  `/img/slow/*` behind a 150 ms delay), because a stall is a property of the
  server and a 20 MB blob is both unreviewable and refused by the pre-commit
  hook. Six tests added to `backend/tests/test_fixture_site.py` by `1.4`'s own
  reasoning — a generated shape that quietly stops stalling or stops being
  oversized takes its acceptance test down silently. `make test-api` on that
  file: 17 passed, was 11.
  The dialog fixture opens its dialogs **before** it writes the product, on
  purpose: with the product written first, a sidecar that hung on `alert()`
  would still return the content and A4 would pass against a broken guard.
- **test (acceptance)** — `render/tests/acceptance.test.js`, six cases plus a
  boundary regression guard; `render/tests/helpers/service.js` starts `1.4`'s
  own server and a per-case sidecar as child processes. No mocking library,
  no patched clock; A3 and A5 are settled on observed `timing_ms` and
  observed `pages_since_restart`. Readiness is polled, never slept for.
  A2 asserts `contexts_in_use === 3` once the cap is reached and `<= 3` at
  the moment the fourth is refused — **not "throughout"**, as an earlier
  draft of this log claimed. It reads the queue's own counter, so it catches
  the cap being raised or removed and cannot see a context opened outside the
  queue; `/inspect` sharing the cap is `6.1`'s criterion.
  A3's threshold is 300 ms with the arithmetic written out in the test
  (24 images × 150 ms over ~6 connections ≈ 600 ms, halved for headroom)
  rather than a bare `<`.
  **The boundary guard is not a §6 criterion** and is labelled as such: it
  asserts that `api`, `db` and `bff` do not resolve from inside the render
  container. That is the negative half of the deferred isolation criterion,
  it needs nothing running, and without it an `extra_hosts:` line added later
  reopens "the only real isolation boundary in the stack" with the criterion
  that would catch it still waiting on a task that does not exist.
- **test (mutation)** — the matrix above. **Three of the six were green
  against a broken service on the first pass** (M1, M2, M3). Each is written
  up rather than quietly fixed: M1 is a trap any fixture that writes itself
  from a string literal will set again, M2 is a standing trap for anyone who
  later adds a dialog listener, and M3 is a test that agreed with its own
  comment while the code did something else.
- **reviewer** (fresh context, did not write the code) — 15 findings. Six
  called must-fix; five acted on, one rejected by measurement, and the rest
  recorded here or in Open questions.
  **Acted on:** M3 above, the one that matters — A5 did not exercise the
  drain, and the reviewer traced it statically before any mutation confirmed
  it. The `render_modules` named volume was removed: it is populated from the
  image once and never again, so moving the playwright pin and the image tag
  together (ADR-0016, ADR-0017) would have left the **old driver mounted
  against the new browsers** — the exact mismatch `render.Dockerfile`'s
  header warns about, and `make reset` drops only `pgdata`. The binds are now
  `./render/src` and `./render/tests`, both **read-only**: `./render:/app`
  read-write would have let a page that achieved execution in the one
  container that runs a real browser over operator-supplied URLs rewrite its
  own source on the host. `docs/TESTING.md` §1 and §4 updated. A3 now does a
  discarded warm-up render, because the first `newContext` cost was landing
  entirely in the unblocked measurement; each case's sidecar is stopped at
  the end of its own case rather than at the end of the file, so A3 is not
  timing renders against other resident Chromium instances.
  **Rejected by measurement:** the claim that `server.py`'s base64 PNG
  literal breaks `ruff` E501 and therefore `make check`. It is 102 columns
  against `line-length = 100`, but `ruff check` on that file passes, so does
  `ruff check --select E501`, and so did the full `make check` with that line
  already in place — ruff's E501 exempts a line that is a single
  unsplittable token. The literal is split across two strings anyway, so
  nobody has to re-derive this. Recorded because the project's rule is to
  settle correctness claims by measurement, and this is a case where careful
  static reasoning about a configured lint rule was wrong.
  **Recorded, not changed:** `pages_since_restart` is attributed to the new
  browser when a render drains across a recycle (pre-existing;
  `src/index.js`); `_int_segment` defaults on junk by design; A6 asks Blink
  to lay out 20 MB in one text node at exactly the §3 ceiling — if it ever
  flakes, the fix is to split the filler, never to raise a timeout that
  cannot be raised; `freePort()` closes its probe before handing the port
  over, which is now documented in the helper.
- **integrator** — `make check` green on a clean tree; the full mutation
  matrix re-run after the review fixes, all seven red with a green baseline.
  `make test-render`: 24 passed, was 17 before this slice.

## Open questions

1. **Spec 012 §6's network-isolation criterion has no owning task.** It needs
   the stack up, so it cannot live here. `5.10` is the nearest fit but its
   text says "sizing, not behaviour", which excludes it. Either `5.10`'s
   wording widens or a new task is added. **For the human** — do not resolve
   by quietly widening `5.10`.
2. **"No `playwright` in the Python image" is asserted nowhere** and costs
   about ten lines. Recommend it lands in `1.7`; it could land here instead
   if the operator would rather close the §6 list faster than keep `1.5`'s
   scope exactly as BUILD_PLAN words it.
3. **`docs/WORKFLOW.md` §1 and §4 use `feat: claim query with SKIP LOCKED
(1.5)` as the commit-message example.** The claim query is `1.8` in the
   current plan. Stale example, nothing depends on it; not fixed in this
   slice to keep the diff on one task.
4. **The formatting gate is wider open than the known defect says.** The
   defect on record is that `make lint` runs `prettier --check .` inside
   `bff` only, so `docs/` is formatted but never gated. Measured here: there
   is **no prettier config anywhere in the repository** — no `.prettierrc`,
   no `prettier.config.*`, no `prettier` key in either `package.json` — so
   prettier runs on its 80-column defaults, while `render/src/` is written at
   roughly 110. `render/src/index.js` therefore **already fails
   `prettier --check` on `develop`**, before this branch touched it.
   Nothing in this slice is prettier-formatted, deliberately: formatting the
   new files to 80 columns would make them inconsistent with the `render/`
   code beside them, and formatting `render/` would be a repo-wide diff that
   collides with anything in flight. The fix is a root `.prettierrc` plus a
   widened `make lint`, which is an ops slice of its own. **For the human.**
   Worse than the formatting: **nothing lints `render/`'s JavaScript either.**
   There is no `eslint.config.*` under `render/` and no `lint` script, and
   `make lint` is `lint-api` + `lint-bff` + `lint-web`. The pre-commit `FMT`
   list covers `.md/.json/.yaml/.yml/.css/.html` but not `.js`. So the three
   JavaScript files in this diff are seen by no linter at all — and neither
   is the service that shipped in phase 0.
5. **Spec 012 §3 says the response cap "truncates and flags, never streams
   whole", but `index.js` does `truncateHtml(await page.content())`** — the
   whole 20 MB string is materialized in the sidecar before being cut. `A6`
   observes the response and so passes either way. Flagging rather than
   changing it: the fix is a streaming `page.content()` that Playwright does
   not offer, and the limit that matters (what crosses the wire) is enforced.
