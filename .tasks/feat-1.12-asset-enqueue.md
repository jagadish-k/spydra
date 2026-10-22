# feat/1.12-asset-enqueue

**Task:** BUILD_PLAN `1.12` · **Spec:** `specs/002-scheduler.md` §7,
`specs/008-assets.md` §1 step 1 · **ADRs:** **0003 (three pools one gate)**,
0002, 0008

**Goal.** The scheduler half of the asset pipeline, and only that half: a
page worker resolves image URLs, inserts `asset_queue` rows and **moves on
without ever blocking on an image** (ADR-0003), and page claiming slows once
the pending queue passes 10,000 (spec 002 §7).

**Nothing drains the queue until `5.2`.** Spec 008's own header says so.
Building the `AssetGate` or the asset pool here would be building them for no
consumer, and the backpressure would have nothing to count.

---

## Measured before writing anything

1. **`asset_queue.observation_id` is `NOT NULL` with an FK to
   `page_observations`**, so the enqueue cannot precede the observation
   write. It is a child of `1.11`'s row, which is why it is a step in the
   page path rather than a pool of its own.
2. **`UNIQUE (observation_id, source_url)` already exists**, so a page whose
   gallery lists the same image twice is a conflict rather than a duplicate
   row. `ON CONFLICT DO NOTHING` is the enqueue's shape, not a retry loop.
3. **`1.4` serves a 150 ms delay per image** (`/img/slow/<name>`, 24 of them
   on `vantage-abrasives/product-images.html`). That delay was built for
   spec 012's `block_resources` criterion and it is exactly what makes
   "never blocks on an image" falsifiable here — see the decisions.
4. **`1.11` already has a definition of "this value is an asset URL"**: the
   `content_hash` exclusion (spec 003 §4). Two definitions of that would
   disagree in the worst direction — a URL excluded from the hash but not
   enqueued is an image that is invisible to both change detection and the
   asset pipeline.

## Decisions

- **One definition of "asset URL", two callers.** It moves to
  `extraction/assets.py`; `hashing.py` imports it. The hash excludes exactly
  what the enqueue picks up, so a value cannot fall between them. This is
  ADR-0027's "one predicate, three callers" reasoning applied to the other
  predicate this project now has.
- **Enqueue by value, not by field name.** Same reasoning as `1.11`'s
  exclusion: `field_vocabulary` is phase 4, and a hardcoded `images` /
  `image_urls` / `thumbnail` list would miss the fifth name a template
  picks. **Cost, stated:** a URL-valued field that is genuinely a link (a
  manufacturer's page) is enqueued as an asset. Spec 008 §2's content-type
  allowlist — verified against the **bytes**, not the header — is what
  rejects it in `5.2`, so the cost is one wasted fetch per page, not bad
  data. Raised below.
- **Order is preserved and `position` is the index.** A gallery is ordered
  and `observation_assets.position` exists to carry that. Deduplicated
  first-wins, so the first occurrence keeps its position.
- **The writer enqueues; `1.13` cannot forget to.** `asset_queue` rows are
  children of an observation, so the page path is one unit of work. The
  alternative — surfacing the URLs on `WriteOutcome` for `1.13` to insert —
  leaves a silent failure mode where a refactor drops the second call and
  the only symptom is an empty asset queue months later.
- **"Never blocks on an image" is proven against the delayed fixture**, not
  asserted. Six `/img/slow/` URLs cost 900 ms to fetch and the enqueue must
  finish in a small fraction of that. A test that only counted rows would
  pass against an enqueue that downloaded every image first, which is the
  one failure ADR-0003 names.
- **The backpressure band is stateful, and that is the point.** Spec 002 §7
  engages above 10,000 and releases below 8,000 — a stateless
  `pending > 10_000` would release at 10,001 and flap across one row, which
  is the behaviour the two numbers exist to prevent. The band therefore
  holds one bool.
- **The pressure check is a separate object from the claim loop**, which
  `1.13` owns. `1.12` ships the mechanism and the measurement; the
  composition is one call in `1.13`.
- **The pending count is one query against the partial index** spec 001 §1
  already defines (`ix_asset_queue_pending_host WHERE state = 'pending'`).
  Counted per claim rather than cached: a cache would be a second source of
  truth for a number that exists to be current, and `5.5` re-tunes the
  threshold against real volume anyway.

## Files this slice owns

```
backend/spydra/extraction/assets.py                   (NEW - the one predicate)
backend/spydra/extraction/hashing.py                  (imports it)
backend/spydra/adapters/postgres/assets.py            (NEW - enqueue + count)
backend/spydra/scheduler/asset_pressure.py            (NEW - the band)
backend/spydra/observations/writer.py                 (enqueues after the insert)
backend/tests/extraction/test_asset_urls.py           (NEW)
backend/tests/adapters/postgres/test_asset_enqueue.py (NEW)
backend/tests/scheduler/test_asset_pressure.py        (NEW)
docs/BUILD_PLAN.md                                    (tick 1.12)
```

## Done when (BUILD_PLAN 1.12)

- [x] A page yielding six images leaves six `asset_queue` rows, in page
      order, with `position` 0–5 and the host normalised.
- [x] The page worker's own timing is unchanged: six `/img/slow/` URLs are
      enqueued in less than the time ONE of them takes to download, with a
      control fetch in the same test proving the route is still slow and the
      fixture server's request log proving nothing else was fetched.
- [x] A queue of 10,001 pending rows measurably slows three real frontier
      claims; 7,999 does not. Observed timestamps, real rows, real count
      query.
- [x] The band releases below 8,000 and not at 10,000 — the 9,000-from-each-
      side test is the only one that can tell a band from a threshold.
- [x] Mutation: **22 mutations, all red.** The first pass left one green: the
      one-definition invariant test used URLs that a narrowed copy of the
      predicate (`startswith("https://cdn.")`) would also have excluded, so
      the test that exists to catch divergence could not see it. Its fixture
      now carries two schemes, four hosts, a port and upper case.
- [x] `make check` green.

## Found while building

- **`position` restarted at 0 on every call**, so two enqueues for one
  observation produced two rows at position 0 — and `5.2` copies that column
  into `observation_assets.position`, where a duplicate is a gallery in an
  undefined order. The writer always enqueues a whole gallery in one call, so
  nothing in the ordinary path would have shown it; a test that drained
  "position 0" hit two rows. The statement now offsets by the observation's
  current maximum.
- **ADR-0026's claim starves on an eligible domain with an empty queue.** The
  claim locks the single most-eligible domain and then claims a row _of that
  domain_, so a second `active` domain with no pending URLs makes `claim()`
  return `None` while rows wait under another host. It cost three `None`
  claims in the backpressure test, which read exactly like a broken brake.
  Not a `1.12` defect — the claim is `1.8`'s and ADR-0026 is explicit about
  locking one domain — but `1.13`'s claim loop must not treat a `None` claim
  as "the frontier is empty", and a multi-domain run will spend claims on
  whichever domain is most eligible rather than on whichever has work.
  **Raised for `1.13`.**

## Open questions

1. **Enqueue by value means a non-image URL field is enqueued** (above).
   Phase 4's field vocabulary is where a field can declare what it is. **For
   the human.**
2. **Nothing emits the queue depth yet.** Spec 002 §7 says the current depth
   "is emitted on every progress event — it belongs on screen rather than in
   a log", and `run_events` emission is `2.8`. The count is exposed here for
   that consumer to read. **Noted, not a decision.**
