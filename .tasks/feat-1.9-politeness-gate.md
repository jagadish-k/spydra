# feat/1.9-politeness-gate

**Task:** BUILD_PLAN `1.9` · **Spec:** `specs/002-scheduler.md` §2, §4, §5, §9
**Ports:** `Fetcher` (robots), `Clock`, `Frontier` (`Completion`,
`abandon_domain`) — all from `1.2`/`1.8`
**ADRs:** **0004 (a block stops the crawler; never retried through)**, 0008,
0026, 0030

**Goal.** The component that decides _when_ a domain may be fetched and
_whether_ it still may be. `robots.txt` once per domain per run with
`Crawl-delay` as a floor and 5xx failing closed; jitter in [0.7, 1.3]; the ×2
backoff capped at 15 minutes; the 10% decay on success; and three
consecutive 403s pausing the domain and abandoning its queue rows.

**ADR-0004 is the whole point of this slice.** The operator named being
blocked as the worst outcome, and standard HTTP client behaviour — retry with
backoff — is exactly wrong against a block. So the hard rule here is
negative: **no path retries through a 403.**

---

## Measured before writing anything

1. **There is no `configured` crawl delay anywhere.** `domains` has one
   `crawl_delay_ms` column (spec 001 §1), and spec 002 §4 says a success
   should "decay `crawl_delay_ms` toward **its configured value** by 10% per
   success, never below it". Once the ×2 backoff has doubled the column,
   the configured value is **gone** — there is nothing to decay toward.
   Raised below; the gate takes the floor as an explicit argument so the
   arithmetic is at least honest about needing it.
2. **`urllib.robotparser` is in the standard library** and parses from a
   list of lines (`parse()`), so no network and no new dependency
   (AGENTS.md). It exposes `can_fetch()` and `crawl_delay()`.
3. **The robots fixtures from `1.4` already encode the floor case**:
   `crawl-delay.txt` carries `Crawl-delay: 10` with a comment saying it must
   raise a 2 s configured delay and must not lower a 30 s one.
4. **`Frontier.abandon_domain()` exists** from `1.8`, so the 403 path has
   somewhere to put the work it stops.

## Decisions

- **The gate computes; it does not persist.** It returns `Completion` values
  and a decision; `1.8`'s frontier writes them in one transaction. The port
  docstring already fixes this division, and `1.8` has a test asserting no
  politeness arithmetic appears in the frontier's SQL. This slice is the
  other side of that assertion.
- **Jitter comes from an injected `random.Random`.** Seedable, so the
  arithmetic is testable exactly — and _separately_, the distribution is
  asserted over many draws so a jitter that always returns 1.0 cannot pass.
  Spec 002 §2: "Fixed intervals are a bot signature"; a test that only
  checks `0.7 <= f <= 1.3` passes against a constant 1.0, which is the thing
  being forbidden.
- **`robots.txt` is fetched through the `Fetcher` port**, not with a bare
  client. It is a request to the supplier like any other, so it carries the
  honest user-agent (ADR-0004) and goes through the same adapter the crawl
  uses. Spec 002 §5 makes it part of the politeness path rather than a
  special case bolted on beside it.
- **Fail closed on 5xx, and that includes `FetchFailed`.** Spec 002 §5 says a
  5xx or a timeout means "treat the domain as disallowed for this run —
  failing closed is correct when the site cannot tell you its rules". A
  `FetchFailed` from the port _is_ the timeout case, so it lands here rather
  than being an unhandled path.
- **Three 403s is a property of consecutive failures, not of 403s.** Spec
  002 §4 increments `consecutive_failures` on 403, 429 and 503 alike, and
  ADR-0004 pauses on "three consecutive 403s". Those two cannot both be read
  off one counter, so the gate tracks 403s separately from the general
  failure count. Named here because a single counter is the obvious
  implementation and it would pause a domain after one 403 and two 429s —
  which is a pause the operator did not earn.

## Files this slice owns

```
backend/spydra/scheduler/__init__.py                (NEW)
backend/spydra/scheduler/politeness.py              (NEW)
backend/spydra/scheduler/robots.py                  (NEW)
backend/tests/scheduler/test_politeness.py          (NEW)
backend/tests/scheduler/test_robots.py              (NEW)
backend/tests/scheduler/test_politeness_observed.py (NEW — real gaps)
docs/BUILD_PLAN.md                                  (tick 1.9 — in the PR)
```

**Not owned:** the frontier and its SQL (`1.8`'s), the fetchers (`1.6`/`1.7`),
`spydra/domain/` (nothing needs changing).

## Acceptance

From spec 002 §9, TESTING.md §2's politeness list, and ADR-0004.

- [x] **F1** `Crawl-delay: 10` raises a configured 2 s delay to 10 s.
- [x] **F2** `Crawl-delay: 1` does **not** lower a configured 2 s delay.
      Both, or "floor" is untested.
- [x] **F3** A 4xx on `robots.txt` means no restrictions.
- [x] **F4** A 5xx on `robots.txt` skips the domain for the run, and so does
      a `FetchFailed`. Failing closed.
- [x] **F5** `robots.txt` is fetched **once per domain per run** and the
      result is reused — asserted on the number of fetches, not on the
      answer.
- [x] **F6** `Disallow` is honoured for our user-agent, falling back to `*`.
- [x] **F7** `respect_robots = false` overrides, and **logs every time it
      takes effect** (spec 002 §5 says "logged every time", so the assertion
      is on the log, not on the behaviour alone).
- [x] **F8** 429 and 503 double `crawl_delay_ms`, capped at 15 minutes, and
      increment `consecutive_failures`. The domain stays **active**.
- [x] **F9** A 403 increments `consecutive_failures` and does **not** back
      off — and nothing anywhere retries it (ADR-0004).
- [x] **F10** Three **consecutive** 403s pause the domain and abandon its
      queue rows. The third one, not the second or the fourth.
- [x] **F11** A 403 → 200 → 403 → 403 sequence does **not** pause: the
      counter resets on success, which is what "consecutive" means.
- [x] **F12** One 403 plus two 429s does **not** pause. Spec 002 §4
      increments the same counter for all three, so reading the pause off it
      would pause a domain the operator did not earn.
- [x] **F13** A 2xx resets `consecutive_failures` to 0 and decays
      `crawl_delay_ms` by 10%, never below the floor.
- [x] **F14** Jitter lands in [0.7, 1.3] **and varies**: over many draws the
      values are not all equal. A range check alone passes against a
      constant 1.0, which is the bot signature spec 002 §2 forbids.
- [x] **F15** **Observed** inter-request gaps for one host show jitter
      rather than a constant — real elapsed time, no mocked clock
      (TESTING.md §2).
- [x] **F16** No 5xx-other response produces a domain-level penalty
      (spec 002 §4's last row): the row is retried by the frontier's
      attempts, and the domain is untouched.

- [x] **F12b** Two 429s followed by **one** 403 does not pause either. The
      ordering F12 does not reach, and the one the single-counter bug fires
      on — see the matrix.

## Mutation matrix

Twenty-five mutations across the two modules, each applied alone. Baseline:
38 passed. **All red** — after the gap below was closed.

| Mutation                                          | Red               |
| ------------------------------------------------- | ----------------- |
| a 403 backs off (a slower retry is still a retry) | F9                |
| `BLOCK_THRESHOLD` 2, and 4                        | F10               |
| pause without abandoning the queue                | F10               |
| **403s read off `consecutive_failures`**          | **F12b only**     |
| a success does not reset the 403 count            | F11               |
| a rate limit resets the 403 count                 | F12, and one more |
| the backoff is uncapped / absent                  | F8                |
| the decay goes below the floor / is absent        | F13               |
| a 500 is charged to the domain                    | F16               |
| the jitter is a constant 1.0                      | F14, F15          |
| the jitter is computed and then ignored           | F15               |
| `Crawl-delay` becomes a ceiling                   | F1, F2            |
| no `Crawl-delay` read as zero                     | F2                |
| a 5xx fails **open**                              | F4                |
| a `FetchFailed` escapes instead of failing closed | F4                |
| a 4xx fails closed                                | F3                |
| `Disallow` ignored                                | F6                |
| the cache keyed by host only / absent             | F5                |
| the override is not logged                        | F7                |
| our user-agent token ignored, wildcard only       | F6                |
| `robots.txt` fetched with the wrong user-agent    | F7                |

### The one gap, and why it was invisible

`forbidden = state.consecutive_failures + 1` — reading the pause off the
shared counter — passed **all 24** of the first tests, including the one
written specifically for it ("one 403 and two 429s does not pause"). In that
sequence the 403 comes first, so the two counters agree and the mutation
cannot show.

Reverse the order and they diverge: two 429s leave the shared counter at 2,
so the **first refusal the site ever sends** reads as the third and pauses
the domain immediately. ADR-0004's cost paragraph accepts that "a transient
403 pauses a domain that would have recovered" on the basis that three
consecutive refusals are strong evidence — one refusal after two busy
responses is evidence of nothing, and the operator still resumes it by hand.

The lesson is about ordering rather than coverage: both tests exercise the
same three outcomes, and only one of the two orderings distinguishes
correct from broken.

## Handoff log

- **planner** — contract above. Two things found before any code: there is
  no column to decay toward (1), and the pause cannot be read off the same
  counter spec 002 §4 increments (Decisions).
- **backend** — `PolitenessGate` is pure arithmetic returning `Decision`
  values; `RobotsCache` is the only thing that performs I/O, and it goes
  through the `Fetcher` port so `robots.txt` carries the honest user-agent
  like any other request (ADR-0004, spec 002 §5). `urllib.robotparser` from
  the standard library, fed lines rather than a URL, so no new dependency and
  no network of its own.
  The gate **never sleeps** — it returns a time and the worker waits. A gate
  that slept would hold the claim, and therefore the domain's `in_flight`
  gate, for the whole politeness delay, which ADR-0026 says a crawler cannot
  do. There is a test for that.
  `on_forbidden` deliberately does **not** back off. Backing off is a slower
  retry, which is still a retry, and ADR-0004's whole argument is that a site
  which has decided to refuse us reads continued requests as confirmation.
- **test** — 38 tests in three files, and the split is the point. The seeded
  file proves the arithmetic exactly; the **observed** file uses the real
  clock and the real RNG, waits the gaps the gate asks for, and asserts on
  the intervals a supplier would see. Neither is sufficient alone:
  `ports/clock.py` warns that a Clock-substituting test "passes while the
  crawler is rude to a real supplier", and the observed file is what catches
  a gate that computes jitter and then returns a time nobody waits for.
  The jitter assertion checks that values **differ** as well as that they are
  in range — a range check alone passes against a constant 1.0, which is
  exactly the bot signature spec 002 §2 forbids.
  The robots tests read `1.4`'s fixture files off disk rather than inlining
  them, because `crawl-delay.txt` carries a comment stating the two
  assertions it exists for and a copy here would let the two drift apart.
- **test (mutation)** — the matrix above. One gap, closed, and it was
  invisible for a reason worth remembering: the ordering of the sequence,
  not the coverage of the outcomes.
- **integrator** — `make check` green (255 Python tests), after one failure
  that only the **full suite** produced.
  `test_respect_robots_false_overrides_and_logs_every_time` passed in
  isolation and failed under `make check` with zero log records. Measured
  rather than guessed: in the full suite `logger.isEnabledFor(WARNING)`
  returned **False** while the effective level was 30 and `logging.disable`
  was 0 — a stale entry in `Logger._cache`, left by another test's logging
  manipulation. `logging` caches enablement per level and invalidates it
  only on some paths, so a test that merely sets a level can still be
  silently muted by whatever ran before it.
  The test now attaches its own handler to the module logger, forces the
  level, clears the cache, and **asserts the logger is live before it
  starts** — that last assertion is what turns a confusing "the code did not
  log" into "the test was muted".
  Worth carrying forward: **every test that asserts on a log is exposed to
  this**, and spec 009's observability work in `1.13` and `5.11` is almost
  entirely log assertions.

## Open questions

1. **Spec 002 §4's decay has nothing to decay toward.** `domains` carries
   one `crawl_delay_ms`, so the ×2 backoff destroys the configured value and
   "never below it" has no referent. Three ways out: add
   `configured_crawl_delay_ms` to `domains` (a migration, and the honest
   fix); keep the backoff multiplier in a separate column and derive the
   effective delay; or treat the robots floor plus a constant default as the
   floor, which is what this slice does because it needs _something_ and a
   migration belongs with a decision. **For the human** — this wants an ADR
   or a schema change, and until then a domain that has backed off once
   decays toward a default rather than toward what the operator set.
