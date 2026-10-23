# feat/2.5-trap-defences

**Task:** BUILD_PLAN 2.5 · **Spec:** 004 §3 (traps), §1 (the keep-rule list
the new rejects extend), §5 (cap/calendar acceptance); 002 §4 (the halt
precedents) · **ADRs:** 0002, 0004 (the pause this is deliberately unlike),
0026 (the race lesson), **0040 (new — backend writes it, content below)**

Stacked on `feat/2.4-dedupe-recrawl` (#26).

## Contract

**The four traps terminate because a named defence fired, and a run that
breaches the per-domain URL cap is failed with the cap named as the reason —
never a clean finish — while the domain itself stays `active`.**

### Already satisfied — do not rebuild

- **Depth cap**: 2.3, `discover`'s `depth >= max_depth` reject against
  `domains.max_depth`. Pinned by `test_links.py` and the worker tests.
- **Scheme rejects**: 2.3, the `_SCHEMES` check → reject reason `scheme`
  (`mailto:`/`tel:`/`javascript:`, checked before canonicalisation).

BUILD_PLAN 2.5's line lists both; they are done. This slice adds the length
reject, the calendar reject, repeating-path detection, and the cap.

### New `discover()` rejects (spec 004 §3), in `discovery/links.py`

Three new `RejectReason`s, sharing the existing tally (counts, ≤5 samples,
first-reason-wins, deduped before tallying per 2.3's fix):

1. **`too_long`** — the **canonical** URL exceeds 2,000 characters. Canonical,
   not raw: the canonical form is what is hashed and enqueued, and a href
   padded by tracking parameters is not a trap. Checked after
   canonicalisation, alongside the other path-based rejects.
2. **`calendar`** — the canonical **path** matches `/20\d\d/\d\d/`, unless the
   link matched an `allow_pattern`. **The escape is `allow_patterns`**: §1
   rule 3 already makes an allow match the operator's explicit yes, so the
   calendar check runs _after_ the allow check and a matched link walks past
   it. This reads coherently with §3's "unless explicitly allowed" — the
   operator's reviewed pattern is the explicit permission — and costs no new
   mechanism. (A broad `^/shop/` allow implicitly permits calendars; the
   dry-run reports them — 2.10's seam, not ours.)
3. **`repeating_path`** — the canonical path's segments contain **one
   contiguous block of one or more segments repeated three or more times in
   immediate succession**. `/a/b/a/b/a/b/` trips on `a,b`; `/x/deeper/deeper/deeper/`
   trips on `deeper`. Reject at the third full repetition — a 2.5-cycle path
   (`/a/b/a/b/a/`) does not trip; one more hop does. Spec 004 §3's example is
   the bug _family_; the threshold is the third repetition. Both trap shapes
   in the fixtures must trip it (see acceptance 1) — an implementation that
   only detects single-segment runs passes one and fails the other, and that
   is a mutation to prove red.

Filter order becomes: `off_host` → `not_allowed` (allow) → **`too_long` →
`calendar` → `repeating_path`** → `deny_pattern` → `depth`. The three
structural rejects sit between the operator's yes and the operator's no:
`calendar` must follow allow (the escape), and the trio stays together.

### The cap

- **Column**: `domains.url_cap INT NOT NULL DEFAULT 20000 CHECK (url_cap > 0)`
  — one Alembic revision, both ways. It lives on the domain for the same
  reason `max_depth` does (2.3's decision: operator-editable per-domain
  crawl shape). **Not** added to the YAML loader (it dies in 3.2); tests set
  it by SQL; a UI field is 3.x.
- **What counts**: every `crawl_queue` row for the `(run_id, domain_id)` —
  all states. `UNIQUE (run_id, url_hash)` already makes row count == distinct
  discovered URL count within a run; abandoned and failed rows still count,
  because they were work discovery produced. State it in the ADR.
- **Enforcement — a count guard inside `_ENQUEUE`, not a separate step**: the
  existing guarded insert gains
  `AND (SELECT count(*) FROM crawl.crawl_queue q WHERE q.run_id = :run_id AND
q.domain_id = :domain_id) < :cap`. One round trip. A batch is
  all-or-nothing: while the count is below the cap the whole batch inserts
  (it may overshoot); at or past the cap nothing inserts. No partial batches.
- **The race, stated honestly (ADR-0026 in view)**: this is deliberately
  _not_ an exact invariant. Two concurrent enqueuers can each see a count
  below the cap and both insert — an overshoot bounded by one batch per
  concurrent enqueuer, after which the count is at or past the cap and every
  further enqueue refuses. Contrast ADR-0026, where politeness is exact and
  lock-enforced; a trap defence with a fuzzy edge is correct, and the
  statement-snapshot race is the price of no per-link round trip. In the ADR.
- **The signal**: the same statement returns `(added, capped)` — `capped :=
count-after-insert >= cap`. It travels as the enqueue's return value;
  `Frontier.enqueue` grows a `cap` keyword and returns a two-field outcome
  (one caller: `PageCrawler._discover`, which has the domain loaded).

### The breach — a run-scoped halt that does not touch the domain

One new frontier method, **one statement, one transaction**:

```sql
WITH abandoned AS (
    UPDATE crawl.crawl_queue SET state = 'abandoned'
    WHERE run_id = :run_id AND domain_id = :domain_id AND state = 'pending'
    RETURNING 1
), halted AS (
    UPDATE crawl.runs
    SET state = 'failed', stop_reason = :reason, finished_at = now(), stats = <_STATS>
    WHERE id = :run_id AND state = 'running'
    RETURNING 1
)
SELECT (SELECT count(*) FROM abandoned) AS abandoned,
       (SELECT count(*) FROM halted) AS transitioned
```

- Atomic, so no worker death can leave the rows abandoned but the run
  drainable into a clean `completed`. `state = 'running'` makes it
  first-signaller-wins: later in-flight pages' idempotent re-signals return
  `transitioned = 0` and log at debug, not error.
- **Run state `failed`, not `stopped`**: `stopped` is reserved for the
  operator's stop (2.7); a breach is system-initiated against a template
  defect, and `failed` with a reason is what tells the operator to act.
- **`stop_reason` is the named reason**, exactly:
  `url cap exceeded: {cap} urls queued for {host}`. Tests assert it names the
  cap and the host.
- **`stats` reuses `_STATS`** (runs.py) in the same statement — share or move
  the constant, do not duplicate the SQL — so `pages_abandoned` is populated
  on the failed run. That plus the terminal state is what makes it "not a
  clean finish"; either alone is weak.
- **The domain row is untouched** — stays `active`, no counter to reset: the
  next run's `(run, domain)` count starts at zero, below any cap, so the next
  run starts clean by construction. This is why the design is run-scoped
  rather than a domain state.
- **Logging**: one structlog `error` line (`url_cap_exceeded`, fields: cap,
  abandoned, host, action "review the domain's discovery rules; the next run
  starts clean"), emitted only by the caller that transitioned the run
  (spec 009 §1: errors are rare; the in-flight tail after a breach is
  bounded by `max_concurrency` and logs at debug).
- **`run_events` does not exist yet (2.8)** and is not built early. The seam:
  2.8 adds a `run_state` event row for the breach so SSE clients see it;
  everything 2.5 records (run row + one error line) is what 2.8 replays.
- **Seeds are not capped**: the loader's own `_ENQUEUE` (configuration.py)
  is the operator's hand-given list and is untouched. A seed set above the
  cap surfaces as a breach on the first discovery enqueue, or completes
  uncapped if nothing discovers — stated, not defended against.
- **2.10's seam**: spec 004 §3's "the report names the pattern that
  exploded, grouped by the discovery rule" is the dry-run's report, built on
  this same `discover()` whose `rejected` mapping already keys by reason and
  by `deny_pattern:<pattern>`. 2.5 adds the reasons; 2.10 reports them. No
  second implementation (ADR-0019's rule, by analogy).

## Decided (user)

- **Cap breach is a run-scoped halt.** On breach: that domain's pending rows
  in that run are abandoned, further enqueues for that (run, domain) are
  refused, **the domain itself stays `active`** — its state does not change.
  The breach is named as the reason — never reported as a clean finish.
  Rationale: a trap is a template defect, not a site refusal (unlike 3×403 →
  paused, ADR-0004); the operator fixes the rule and the next run starts
  clean.
- **An ADR is required** (it is a structural decision: a new halt kind that
  does not touch domain state, unlike 1.11's broken-template halt and
  ADR-0004's pause). **ADR-0040**, the next free number. The backend agent
  writes the file; the content is this section plus the contract's cap
  decisions: enforcement shape and its bounded race, what counts toward the
  cap, the run-scoped halt that leaves the domain `active`, `failed` +
  `stop_reason` + `stats` as the recording, and the 2.8 event seam.

## Decided (planner)

Verified on `feat/2.4-dedupe-recrawl` @ `351332d`, clean tree:

- **The traps and their entry points** (2.1's catalogue, 1.4's server):
  - **Facet explosion** — `form.facets` on every leaf listing (`_facets`),
    each link adding one value to the query; reachable space ≈ 2^5·2^5·2^3·2^3
    per page of every leaf. Kept out only by `EXIT_DISCOVERY`'s
    `deny_patterns`; the breach test drops that deny. This is the cap trap.
  - **Relative-link loop** — footer entry `/shop/loop/x/page`; every loop
    page (`section.subcategories` tile) links `loop/x/page` _relatively_, so
    each hop appends one `loop/x/` pair: `loop,x` × k. Entry points:
    `test_links.py` `LOOP`, the footer via `footer.site-footer a`.
  - **Calendar** — footer entry `/shop/news/2026/10/`; `_news` pages link the
    next month `rel="next"` (matched by `next_page` rules), without end. The
    entry URL itself matches the calendar pattern, at depth 1 — below the
    depth cap, so only the calendar reject stops it.
  - **Long** — footer `/shop/search?q=` + `x`×2100 (`LONG_URL_LENGTH`);
    still > 2,000 after canonicalisation (`q` is not a tracking parameter).
  - **Single-segment repetition** — 1.4's `/trap/` (`server.py`
    `TRAP_PREFIX`): each page links `<path>/deeper/`, so `/trap/deeper/deeper/deeper/`
    is `deeper` ×3. Served on any host the fixture server answers, so a
    worker test can seed `halden.test/trap/` with a listing template whose
    discovery matches `a`.
  - The footer is on every Halden listing page (`_rejects()`); the
    established way to reach it is `subcategory_links` widened with
    `footer.site-footer a` (2.3's test pattern). `EXIT_DISCOVERY` alone does
    not match the footer — the trap tests widen the rule.
- **The guarded enqueue is the right seam** (`frontier.py` `_ENQUEUE`): one
  statement, `unnest`, `FOR SHARE` on the domain, run-`running` guard,
  `ON CONFLICT DO NOTHING`. The cap guard joins those guards; the count
  doubles as the durable breach flag because rows within a run are never
  deleted — no new state, and refusal after breach is self-healing.
- **`runs.stop_reason` and the `failed` state exist since 1.1** (migration
  `8c1d4a9f5e02`, `run_state` enum running/paused/completed/stopped/failed)
  — the named reason needs no migration. Nothing sets a non-completed
  terminal state today; this is the first, on the path 2.7 generalises.
- **`_STATS` computes `pages_abandoned` already** (runs.py) — reuse it in the
  breach statement rather than inventing a second stats shape.
- **The breach path composes like the existing halts**: `_observe`'s
  broken-template halt and `_pause_if_blocked`'s 403 pause both do
  abandon-then-log from the crawler; the difference is that those touch
  domain state and this deliberately does not, and that this one is one
  atomic statement because "rows abandoned but run still drainable into
  `completed`" is exactly the clean finish the acceptance forbids.
- **One enqueue caller** (`crawl.py:334`); the port signature change is
  contained. Seeds go through `configuration.py`'s own `_ENQUEUE` (above).
- **The natural fixture arithmetic**: from `/shop/cutting/discs/` at
  `max_depth = 5`, the reachable facet space is ΣC(16,k≤5) ≈ 6,885 subsets ×
  ~3 pagination spellings ≈ 20.6k URLs — the default 20,000 is calibrated to
  the fixture but only just, and crawling 20k rows through the worker is far
  too slow for a test. **Breach tests set a low `url_cap` by SQL**; the
  default is asserted as the column/entity default.
- **No BFF/frontend surface**: the new column reaches
  `crawl.generated.ts` via `make drizzle-pull` (`make generated`); no API
  route changes, so `schema.crawler.d.ts` should not move.

## Files this slice owns

- `backend/spydra/discovery/links.py` (three rejects + order)
- `backend/spydra/ports/frontier.py` (enqueue outcome + `cap`; the halt method)
- `backend/spydra/adapters/postgres/frontier.py` (`_ENQUEUE` guard; the halt
  statement)
- `backend/spydra/adapters/postgres/runs.py` (`_STATS` shared, nothing else)
- `backend/spydra/scheduler/crawl.py` (`_discover`'s breach path)
- `backend/spydra/domain/entities.py` (`Domain.url_cap`)
- `backend/spydra/adapters/postgres/domains.py` (read the column)
- `backend/migrations/versions/` (one revision, up and down)
- `docs/specs/004-discovery.md` (§1: the three rejects join the keep-rule
  list; §3: the repeating-path threshold made precise, the calendar escape
  named, the cap's run-scoped semantics)
- `docs/adr/0040-*.md`, `docs/adr/README.md` (backend writes)
- generated regen via `make generated` (`bff/src/db/schema/crawl.generated.ts`)
  — never hand-edited
- `backend/tests/**` (test-writer)
- `docs/BUILD_PLAN.md` (tick — integrator in the PR)

## Acceptance (BUILD_PLAN 2.5, spec 004 §5)

Every crawl below runs the real worker against the fixture site, one
connection, `crawl_delay_ms = 20` (the `seed_halden` substrate; extend, do
not fork).

- [ ] **The loop terminates because of `repeating_path`**: a crawl from
      `EXIT_SEED` with the footer reachable enqueues `/shop/loop/x/page`
      (d1) and `/shop/loop/x/loop/x/page` (d2) and crawls both `done`, and
      **no queue row ever contains three `loop/x` units**; the run
      `completed`. Unit level: `discover` on the k=2 page rejects the k=3
      link as `repeating_path` with a sample, and that link's depth (3) is
      ≤ `max_depth` (5) — depth is not the rejecter. The existing
      k=2-link-is-accepted test (`test_without_base_href…`) stays green.
- [ ] **The single-segment trap terminates too**: a crawl seeded on
      `/trap/` with a rule matching `a` enqueues at most two `deeper` hops
      and never `/trap/deeper/deeper/deeper/`; unit level, `discover` on
      the two-deeper page rejects the third as `repeating_path`.
- [ ] **The calendar is rejected, and the escape works**: unit level,
      `discover` on the seed page (footer rules) rejects `/shop/news/2026/10/`
      as `calendar` with a sample, at depth 1; the same rules plus
      `allow_patterns = ["^/shop/news/"]` accept it. Worker level: a
      footer-reachable crawl queues **zero** `/shop/news/` URLs and
      `completed`.
- [ ] **`too_long` fires**: unit level, the footer's search URL is rejected
      `too_long` with a sample; worker level, no queue URL exceeds 2,000
      characters.
- [ ] **The reject reasons fire, not just the run finishing**: each unit
      assertion above names the reason, a count ≥ 1, and a sample — the
      grouped-reject contract 2.10 reports on (its seam: `rejected` keyed by
      reason / `deny_pattern:<pattern>`).
- [ ] **A breach fails the run with the cap named**: `url_cap` set low
      (SQL, e.g. 200) and the facet deny dropped, a crawl from `EXIT_SEED`
      breaches; the run ends `failed` with `stop_reason` naming
      `url cap exceeded` and the cap; its pending rows for that domain are
      `abandoned` and `stats.pages_abandoned` > 0; **the domain is still
      `active`**; no row is deleted. Adapter level: after the count reaches
      the cap, `enqueue` returns `added = 0, capped = True`.
- [ ] **The overshoot is bounded and every breach signals**: adapter level,
      enqueues past the cap never take the count beyond cap + one batch, and
      each one past the cap signals `capped`.
- [ ] **The next run starts clean**: a following run (re-`apply` or
      re-seeded) on the same domain with the deny restored completes with no
      breach, and the domain was `active` throughout both.
- [ ] **Mutations proven red, then restored**: each new reject's condition
      (excised, and inverted — e.g. `> 2000` → `>= 2000`, the calendar
      regex, the repetition threshold 3 → 2 and the unit length restricted
      to 1); the cap guard (`<` → `<=`, dropped); `capped` (`>=` → `>`);
      the halt statement's `state = 'running'` guard; `stop_reason` emptied;
      the abandon's `domain_id` scope dropped; the calendar escape removed
      (allow no longer escapes); the check order (calendar before allow).
- [ ] `make check` green (generated regen included).

## Handoff log

- planner (subagent session): contract and decisions above, verified against
  `feat/2.4-dedupe-recrawl` @ `351332d` (clean tree; no in-flight slice owns
  any file here). Hand off to **spydra-backend** — first file
  `backend/spydra/discovery/links.py` (the three rejects are the pure half
  the test agent can start pinning while the cap's migration lands);
  **ADR-0040 is backend's to write**, content pinned in Decided (user) +
  the cap sections.
- backend (this session, @ the cap+halt commit): ADR-0040 written and
  indexed; the three `discover()` rejects, the cap, and the breach halt
  built as contracted. `make lint` and `make test-api` green (1050 passed,
  2 skipped — existing tests only; the trap/breach tests are the test
  agent's). Migration verified up → down → up on the dev DB; `make
generated` run (crawl.generated.ts +1 line, no frontend schema movement).
  Deviations, all deliberate:
  - **The halt is one transaction, two statements, not the contract's one
    CTE statement.** PostgreSQL runs data-modifying CTEs on one snapshot
    and they cannot see one another's writes, so the sketch's `_STATS`
    inside the halt CTE would count the just-abandoned rows as still
    `pending` and write `pages_abandoned = 0` — violating the contract's
    own acceptance. The abandon (the existing `_ABANDON`) runs first, the
    guarded `_HALT_RUN` with `_STATS` second, in one transaction: the same
    atomicity against worker death, the same race profile, correct stats.
    Verified on real Postgres with a throwaway script (not committed).
  - **`enqueue`'s `cap` is a required keyword**, no default: a default of
    20,000 would silently re-create the column default in a future caller
    and defeat every low-cap breach test. The signature change's mechanical
    fixes to existing test call sites (`cap=20_000`, `.added`) ride in the
    cap commit — adaptations of existing tests, not new ones.
  - **`adapters/postgres/tables.py` touched** though not in the owned list:
    the Core metadata must carry `url_cap` or the next `make revision`
    autogenerates a spurious drop (the 1.13 `configured_crawl_delay_ms`
    precedent). `runs.py` is untouched — `_STATS` is shared by import into
    `frontier.py`, which satisfies "share, do not duplicate" with zero
    edits.
  - **The calendar regex is `/20\d\d/\d\d(/|$)`**, not the contract's
    literal trailing-slash form: canonicalisation strips the trailing slash
    (spec 004 §2 step 6), so the month-leaf `/shop/news/2026/10` — which
    the acceptance requires rejected — would not match `/20\d\d/\d\d/`.
    Same pattern, boundary made explicit.
  - Spec 004 §3's defence-2 line ("the domain halts for that run") and
    §3a's "URL cap halts the domain" both said the wrong actor; rewritten
    to the run-fails/domain-stays-`active` semantics alongside the pinned
    calendar escape and repeating-path threshold.
    Hand off to **spydra-test**.

## Open questions — for the human

Carried from 2.4 (unchanged): subdomains never followed; AUTO listings with
JS links discover nothing; invalid hand-edited patterns raise mid-crawl.

New:

1. **The repeating-path threshold reading.** Pinned: three _full_ consecutive
   repetitions, so spec 004 §3's literal `/a/b/a/b/a/` (2.5 cycles) is not
   itself rejected — one more hop is. The alternative — a segment value
   recurring at a fixed stride three times, which trips the 2.5-cycle example
   — is fiddlier and false-positives more. The spec edit makes the pinned
   reading explicit; flag if you wanted the stride reading.
2. **The calendar escape is `allow_patterns`**, so a broad `^/shop/` allow
   implicitly permits calendar URLs. The operator's reviewed pattern is
   treated as the explicit yes; the dry-run (2.10) is where that becomes
   visible. Not solved here.
3. **Multi-domain runs.** `runs.domain_ids` is an array, but every
   run-creation path today is 1:1 (`apply`), so failing the whole run on one
   domain's breach is exact. If multi-domain runs ever exist, 2.7's lifecycle
   needs a per-domain stop decision; the seam is the halt statement's
   run-level UPDATE.
