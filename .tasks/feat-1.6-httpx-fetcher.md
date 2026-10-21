# feat/1.6-httpx-fetcher

**Task:** BUILD_PLAN `1.6` · **Spec:** `specs/002-scheduler.md` §4, §6;
`specs/012-render-sidecar.md` §4 (for the boundary this adapter must NOT
cross) · **Port:** `spydra/ports/fetcher.py`, defined in `1.2`
**ADRs that constrain this:** 0004 (never retry through a block), 0008 (ports
and adapters), 0016 (rendering is a sidecar), 0022 (agent team), 0027 (no
required fields), 0028 (httpx2 + MockTransport)

**Goal.** `HttpxFetcher` behind the `Fetcher` port — the static fetch path.
An HTTP error status is a **successful fetch**: 403, 429 and 5xx come back as
a `FetchedPage` carrying that status, because deciding what they mean is the
politeness gate's job (`1.9`, ADR-0004) and not an adapter's.

**Branched from `feat/1.5-render-acceptance`, not from `develop`.** Phase 1
is strictly linear and `1.5` is still in review (PR #8). The file sets are in
fact disjoint — `1.5` is `render/` plus the fixture site, this is
`backend/spydra/adapters/http/` — but both tick a box in
`docs/BUILD_PLAN.md` within a few lines of each other, and stacking avoids a
conflict in the one file they share. **This PR must merge after #8.**

---

## Measured before writing anything

1. **`httpx2` is declared in the `dev` dependency group only**
   (`backend/pyproject.toml`), and `HttpxFetcher` is production code. It
   imports today purely because `uv sync --frozen` installs uv's default
   group set, which includes `dev` — so the _production_ `api` and `worker`
   images are already carrying the dev dependencies, and the one runtime
   dependency this task adds is declared in the wrong place. Moving it to
   `[project].dependencies` is part of this slice; `make lock` re-resolves.
   Verified installed: **httpx2 2.13.1**, with `MockTransport`,
   `TooManyRedirects`, `ConnectError`, `ReadTimeout`, `TimeoutException`,
   and `follow_redirects` / `max_redirects` / `trust_env` on `AsyncClient`.
2. **`httpx2.Response.elapsed` raises** `RuntimeError("'.elapsed' may only be
accessed after the response has been read or closed")`. It would work on
   the path this adapter takes, since it reads `.text` — but `elapsed_ms` is
   measured from the injected `Clock.monotonic()` instead, which is the port
   `1.2` defined for exactly this and does not depend on when the body was
   read.
3. **The `Fetcher` port, `FetchRequest`, `FetchedPage`, `Backpressure` and
   `FetchFailed` all already exist** from `1.2`. This slice adds an adapter
   and changes none of them — if the port needs changing to fit the first
   adapter, the port was wrong, which is the whole reason `1.2` wrote it
   before either adapter.
4. **`ports/fetcher.py`'s docstring numbers the two adapters `1.7` and
   `1.8`.** They are `1.6` and `1.7` in the current BUILD_PLAN — the numbers
   shifted when `1.5` was inserted. Corrected here, since it is a file this
   slice touches. ADR-0028 carries the same stale pair; raised, not edited
   (see Open questions).

## Decisions

- **A supplier's 503 is a status, not `Backpressure`.** This is the one place
  the two adapters genuinely diverge, and it is easy to get backwards.
  ADR-0004 routes a 429 or 503 from a _site_ to backoff with
  `consecutive_failures` incremented; spec 002 §6 routes a 503 from _our own
  sidecar_ to backpressure with no penalty. `HttpxFetcher` therefore never
  raises `Backpressure` — there is no sidecar on this path — and a test
  asserts that rather than leaving it to be inferred from an absence.
- **The user-agent from `FetchRequest` is authoritative over `headers`.**
  `FetchRequest.user_agent` is required precisely so no code path can send
  httpx's default (ADR-0004, and the field's own docstring). A caller passing
  `user-agent` in `headers` must not be able to defeat that, so the UA is
  applied last and a test asserts the override loses. Header matching is
  case-insensitive in httpx2, so the test uses odd casing.
- **`trust_env=False`.** httpx reads `HTTP_PROXY` / `HTTPS_PROXY` from the
  environment by default. ADR-0004 puts proxy rotation explicitly out of
  scope, and an ambient proxy variable silently changing which IP a supplier
  sees — and therefore whether we get blocked — is the opposite of the honest
  identification that ADR asks for. Flagged in Open questions in case the
  operator wants the opposite.
- **Redirects are followed and recorded, not decided about.**
  `follow_redirects=True`; `final_url` is where it ended and `request_url` is
  preserved, which is what makes `FetchedPage.redirected` meaningful.
  Exhausting `max_redirects` produces no response, so it is `FetchFailed`.

## Files this slice owns

```
backend/pyproject.toml                        (httpx2 → runtime dependency)
backend/uv.lock                               (make lock)
backend/spydra/adapters/http/__init__.py      (NEW)
backend/spydra/adapters/http/httpx_fetcher.py (NEW)
backend/spydra/ports/fetcher.py               (docstring: task numbers only)
backend/tests/adapters/http/test_httpx_fetcher.py (NEW)
docs/BUILD_PLAN.md                            (tick 1.6 — in the PR)
```

**Not owned, do not touch:** `spydra/domain/` (the port and the two
dataclasses are `1.2`'s and must not move to fit this adapter),
`spydra/scheduler/` (`1.9`'s), `render/`, the fixture site, anything under
`bff/` or `frontend/`.

## Acceptance

Derived from `1.6`'s "Done when" (status table, timeout, redirect,
`FetchFailed`, user-agent) and from the port's docstring.

- [x] **B1** A 200 returns a `FetchedPage` with the body, `http_status` 200,
      `fetch_path = STATIC`, and `elapsed_ms` from the injected clock.
- [x] **B2** 403, 429, 500 and 503 each return a `FetchedPage` with that
      status and raise nothing. **No `Backpressure` on any of them** — a
      supplier's 503 is a status; only the sidecar's is backpressure.
- [x] **B3** A read timeout raises `FetchFailed`, not a bare
      `httpx2.TimeoutException` — the scheduler depends on the port's
      vocabulary, not the client's.
- [x] **B4** A connect error (DNS, refused) raises `FetchFailed`.
- [x] **B5** A redirect chain ends with `final_url` at the last hop,
      `request_url` unchanged, and `redirected` true; a 200 with no redirect
      has `redirected` false. Both, or the property is untested.
- [x] **B6** The outgoing request carries the user-agent from
      **`.env.example`**, read from the file rather than pasted into the
      test — a copy in the test drifts from the file silently and the
      assertion then proves nothing (ADR-0004).
- [x] **B7** `FetchRequest.headers` reach the wire, and a `user-agent` in
      `headers` does **not** override `FetchRequest.user_agent`.
- [x] **B8** `timeout_ms` reaches the client as seconds, and the 30 s-style
      per-request value is what is used rather than a module default.
- [x] **B9** `aclose()` closes the pool, and the adapter satisfies the
      `Fetcher` Protocol structurally, so a signature drift in either
      direction is caught.
- [x] **B10** A URL httpx2 rejects raises `FetchFailed`. Added after review:
      `httpx2.InvalidURL` does not inherit from `HTTPError`, and the guard
      the handoff log was proudest of had no lettered criterion.
- [x] **B11** A non-ASCII header value raises `FetchFailed`. **Found by
      review, not by the author**, and it is the same family as B10: httpx2
      raises a builtin `UnicodeEncodeError` for a header value it cannot
      encode as ASCII, before any transport is touched. `domains.user_agent`
      is operator-edited TEXT, so `Müller-Abrasives Crawler/1.0` — the
      honest identification ADR-0004 asks for — would have raised out of
      `fetch()` on every claim for that domain and stalled it until the
      lease expired.
- [x] **B12** The production client is the one the suite exercises:
      `build_client(transport=…)` is the seam, the redirect budget is
      asserted by value, and the certificate environment is honoured and
      _reaches the client_.

**Twenty-two chosen mutations, all red** — the honest claim, and not the
same as "every guard is mutation-tested", which an earlier draft of this file
and of `BUILD_PLAN.md` both said. A mutation matrix is evidence about the
mutations in it; review found four guards the first thirteen did not touch
(see the matrix). Break a guard in `httpx_fetcher.py`, prove that test goes
red, restore. On `1.5` three of six criteria were green against a broken
service on the first pass; the step is not optional here either.

## Mutation matrix

Twenty-two mutations against `httpx_fetcher.py`, each applied alone, the
suite run, the file restored. Baseline: 30 passed. **All red.**

| Mutation                                                     | Red              |
| ------------------------------------------------------------ | ---------------- |
| `elapsed_ms = 0`                                             | B1               |
| `elapsed_ms = 2000` — a constant, not a measurement          | B1               |
| `fetched_at = datetime.now(UTC)` — ignore the injected clock | B1               |
| `response.raise_for_status()` — have an opinion about status | B2 (8 cases)     |
| translate a 503 into `Backpressure`                          | B2               |
| `raise` instead of `raise FetchFailed(...)`                  | B3, B4, B10, B11 |
| drop `httpx2.InvalidURL` from the except clause              | B10              |
| drop `UnicodeError` from the except clause                   | B11              |
| `final_url = request.url`                                    | B5               |
| `request_url = response.url`                                 | B5               |
| `{**headers, "user-agent": ua}` — the pre-fix merge          | B7               |
| return the caller's headers unchanged — no user-agent        | B6, B7, B11      |
| return only the user-agent — drop caller headers             | B7, B11          |
| `timeout=20.0` — ignore the per-request value                | B8               |
| `connect=5.0` — one phase differing from the rest            | B8               |
| bound the pool wait                                          | B8               |
| `trust_env=True`                                             | B12              |
| `follow_redirects=False`                                     | B5, B12          |
| `MAX_REDIRECTS = 2`                                          | B12              |
| `verify=True` — ignore the certificate environment           | B12              |
| `_ca_bundle()` always returns `True`                         | B12              |

### What the first matrix missed

The first pass was thirteen mutations and claimed to cover every guard. It
did not, and the four it missed are worth naming because each was green
against a real defect:

- **`fetched_at`** — swapping the injected clock for `datetime.now(UTC)` was
  green. B1 asserted only `tzinfo is not None`, which any aware datetime
  satisfies. The injection is what lets `1.9`'s backoff-decay and
  lease-expiry tests drive observation timestamps, so a refactor away from it
  would have surfaced much later as scheduler tests that cannot control the
  timestamps they assert on.
- **A constant `elapsed_ms`** — the fake clock stepped by a fixed 0.25 s, so
  every fetch measured the same number and `elapsed_ms = 250` was green. The
  clock now advances by a growing step, in whole seconds so the arithmetic is
  exact; a 0.1 s step gives 0.6000000000000001 and `int()` truncates 400 to
  **399**, which is the kind of expected value that gets "fixed" by loosening
  the assertion.
- **Three of four timeout phases** — B8 asserted `read` only.
- **The redirect budget** — `assert client.max_redirects == MAX_REDIRECTS`
  compared the constant to itself, so `MAX_REDIRECTS = 2` was green. That one
  matters: an ordinary canonicalisation chain
  (`http://` → `https://` → `www.` → trailing slash) would exhaust a budget
  of 2, which this adapter correctly reports as `FetchFailed` and `1.9`
  charges to the domain. A healthy supplier would look broken.

The fix for the last one also closed the reason the others were possible: the
suite built its own client that merely _looked_ like production. It now goes
through `HttpxFetcher.build_client(transport=…)`, so anything added there is
covered by all thirty tests instead of none.

## Handoff log

- **planner** — contract above. Four things measured rather than assumed, of
  which the dependency declaration (1) is a real defect in the tree today
  rather than a gap in this task. The port is `1.2`'s and is not touched
  apart from two stale task numbers in its docstring.
- **backend** — adapter in `adapters/http/httpx_fetcher.py`. Two defects in
  the first draft, both caught by measuring httpx2's behaviour rather than
  reading about it, and both of the kind that fail silently:
  **(a)** `{**request.headers, "user-agent": ua}` does **not** replace a
  caller's `User-Agent`. Measured on 2.13.1: a mapping holding both casings
  emits two header lines and `headers.get("user-agent")` returns
  `"caller, ours"` — the caller's value first. HTTP permits the repetition so
  nothing raises; the request simply goes out misidentified, which is exactly
  what ADR-0004 asks `FetchRequest.user_agent` to prevent. The drop is now
  case-insensitive.
  **(b)** `httpx2.InvalidURL` does **not** inherit from `httpx2.HTTPError` —
  it comes straight off `Exception` — so a junk URL out of the frontier would
  have escaped the port's vocabulary and taken the worker loop down with an
  exception `1.9` has no branch for. It is caught by name alongside
  `HTTPError`.
  `elapsed_ms` comes from the injected `Clock.monotonic()` rather than
  `Response.elapsed`, which raises unless the body has been read.
- **test** — 26 tests written from the port's docstring and `1.6`'s criteria,
  never from the adapter. `MockTransport` handlers only (ADR-0028): no
  mocking library, no network, no patched wall clock. Three things worth
  knowing:
  **(a)** the user-agent assertion **reads `.env.example`** rather than
  pasting the value, and additionally asserts the ADR's two substantive
  requirements — a contact route is present, and no browser name appears —
  because "some string was set" is not what ADR-0004 asks for. It asserts on
  `headers.get_list(...)`, not `get(...)`: a `get()`-based check with `in`
  passes against the duplicate-header defect above.
  **(b)** the Protocol conformance check is a `mypy --strict` annotation, not
  `isinstance`. No port in `spydra/ports/` is `@runtime_checkable`, and
  adding that decorator to satisfy a test would be the test changing the
  port — the thing `1.2` wrote the port early to prevent. It is also the
  weaker check, since `runtime_checkable` verifies attribute names and
  ignores signatures.
  **(c)** `tests/adapters/http/` must NOT have an `__init__.py`. With one,
  pytest puts `tests/adapters/` on `sys.path`, the directory name `http`
  shadows the standard library's `http` package, and the whole suite dies on
  `No module named 'http.client'` raised from inside httpx2 — which reads
  like a broken dependency rather than a path problem. Hit while writing this
  file; recorded in the module docstring, where the next person would make
  the same move.
  Most "obviously invalid" URLs do not raise: `http://`, `not-a-url`,
  `ftp://h.test/x` and `http://%zz.test/` all reach the transport. The two
  that actually raise `InvalidURL` were found by measurement and are the ones
  used.
- **test (mutation)** — the matrix above, re-run in full after the test file
  was refactored for `mypy --strict`. The first run was against the
  pre-refactor file and would not have been evidence about this one.
- **reviewer** (fresh context, did not write the code) — twelve findings,
  three called must-fix. All three were real and all three are fixed.
  **The one that mattered:** `UnicodeEncodeError` escaped the port's
  vocabulary — the same family as the `InvalidURL` defect this slice had
  already fixed, and still open. It is the only finding that could take a
  worker down, and the trigger is an operator doing what ADR-0004 asks.
  The other two were coverage, not adapter defects: `fetched_at` had no
  guard, and the redirect budget was asserted against its own constant.
  Both are in the matrix now, along with two more green mutations the
  reviewer found while there.
  **One recommendation rejected by measurement.** The reviewer proposed
  keeping `trust_env=True` and passing `mounts={}` (or `proxy=None`) to kill
  only proxy inheritance, leaving the certificate environment intact. It does
  not work: measured on httpx2 2.13.1, both are ignored while `trust_env` is
  on and the environment proxies still resolve into two mounts. The _finding_
  underneath it was right, though, and better than the fix — `trust_env` also
  gates `SSL_CERT_FILE` and `SSL_CERT_DIR`, so turning proxies off silently
  took the operator's private CA with it, and the failure mode is a
  `ConnectError` → `FetchFailed` → rising `consecutive_failures` → a paused
  domain with nothing anywhere saying "certificate". So `trust_env=False`
  stays and the adapter re-honours that half itself, with a test that asserts
  the context _reaches the client_ — asserting only that `_ca_bundle()`
  returns a context left `verify=True` green.
  **Also acted on:** `pool=None` on the timeout, so our own pool saturation
  is never charged to a supplier (the reviewer's point that spec 002 §6's
  argument about a busy sidecar applies equally to a busy pool of ours); the
  test helper now builds the production client; the two `# noqa: SLF001`
  comments are gone, since `SLF` is not in ruff's `select` and they would
  have become `RUF100` failures the day it is; the orphaned `httpx2` comment
  in `pyproject.toml` no longer reads as the `pytest-asyncio` paragraph's
  opening.
  **Recorded, not changed:** `dict(response.headers)` comma-joins repeated
  headers, so a pair of `Set-Cookie` lines becomes one invalid value — forced
  by `FetchedPage.headers` being a `Mapping[str, str]` from `1.2`, so it
  belongs in `1.7`'s or `1.9`'s task file rather than here, before anything
  starts reading that field. And `FetchRequest.timeout_ms` has no upper
  bound, so a 600 000 would hold a static worker slot for ten minutes —
  the API's or `1.9`'s to bound, not an adapter's.
- **integrator** — `make lock` re-resolved `backend/uv.lock` for the moved
  dependency (two lines). `make check` green: ruff + mypy clean, 30 tests in
  the new file, no generated-file drift.

## Open questions

1. **`trust_env=False` is a judgement call, not a spec requirement.** It
   stops an ambient `HTTPS_PROXY` from silently changing which IP a supplier
   sees, which reads as consistent with ADR-0004 putting proxy rotation out
   of scope — but the operator may well want to route the crawler through a
   proxy they control, and with this setting they cannot do it by
   environment. **For the human:** if the answer is "I want the env to
   work", this flips to `trust_env=True` and ADR-0004 should say so.
2. **ADR-0028 numbers the two adapters `1.7` and `1.8`** (as did
   `ports/fetcher.py` before this slice). They are `1.6` and `1.7` now.
   Corrected in the port because this slice owns it; **not** corrected in the
   ADR, because an accepted ADR's text is not something to adjust in passing.
   Worth a sweep: the renumbering when `1.5` was inserted left stale pairs in
   at least these two places, and `docs/WORKFLOW.md` §1/§4 still call the
   claim query `1.5` when it is `1.8` (raised in `1.5`'s task file too).
3. **The production images carry the `dev` dependency group.** Finding (1)
   above is fixed for `httpx2` specifically, but the underlying cause —
   `uv sync --frozen` with uv's default groups in `docker/api.Dockerfile` and
   `docker/worker.Dockerfile` — is untouched, so `ruff`, `mypy`, `pytest` and
   `pytest-asyncio` are all in the shipped images. That is an ops slice
   (`uv sync --frozen --no-dev` plus a separate test path), not this one.
