# 002 — Scheduler, politeness and the three pools

**Phase 1** · depends on 001 · ADR-0002, ADR-0003, ADR-0004, ADR-0016

This is the component most expensive to get wrong. Being blocked is the
operator's stated worst outcome, and the politeness guarantee is enforced
here or nowhere.

---

## 1. The claim query

One worker, one URL, one domain at a time. The guarantee lives in SQL:

```sql
WITH eligible AS (
    SELECT d.id
    FROM domains d
    WHERE d.state = 'active'
      AND d.next_eligible_at <= now()
      AND d.in_flight < d.max_concurrency
    ORDER BY d.next_eligible_at
    LIMIT 1
)
UPDATE crawl_queue q
SET state = 'in_flight',
    locked_until = now() + interval '120 seconds',
    attempts = attempts + 1
WHERE q.id = (
    SELECT q2.id
    FROM crawl_queue q2
    JOIN eligible e ON e.id = q2.domain_id
    WHERE q2.state = 'pending'
    ORDER BY q2.depth, q2.id          -- breadth-first: listings before products
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING q.*;
```

`domains.in_flight INT NOT NULL DEFAULT 0` is incremented in the same
transaction and decremented on completion. `SKIP LOCKED` means workers never
block each other; they take the next eligible row.

**Order by `depth` first.** Listing pages fan out into product URLs, so
draining them early keeps the frontier full and stops workers starving at the
end of a run.

## 2. After a fetch

In one transaction:

```
domains.next_eligible_at = now()
  + (crawl_delay_ms × jitter)        jitter ∈ [0.7, 1.3]
domains.in_flight -= 1
crawl_queue.state  = 'done' | 'failed'
```

**Jitter is not optional.** Fixed intervals are a bot signature; ±30% is
cheap and removes the regularity.

## 3. Lease expiry

A worker that crashes mid-page leaves a row in `in_flight`. A sweep returns
rows whose `locked_until` has passed to `pending`; three attempts moves a row
to `failed`. The sweep also decrements the owning domain's `in_flight`, which
is why that counter must be reconciled rather than trusted.

Run the sweep at the start of every claim loop iteration — a separate janitor
process is one more thing to supervise.

## 4. Backoff and blocking (ADR-0004)

| Response | Action |
| --- | --- |
| 429, 503 | `crawl_delay_ms ×= 2`, capped at 15 min. `consecutive_failures += 1`. Domain stays active. |
| 403 | `consecutive_failures += 1`. **Three consecutive → domain to `paused`**, remaining queue rows for that domain abandoned, event emitted. |
| 5xx (other) | Retry up to 3 attempts, then `failed`. No domain-level penalty. |
| 2xx | `consecutive_failures = 0`. Decay `crawl_delay_ms` toward its configured value by 10% per success, never below it. |

Never retry through a 403. The abandoned rows stay in the queue marked
`abandoned` so the run report can show the work that was not done, rather than
reporting a clean finish.

## 5. robots.txt

Fetched once per domain per run, cached for the run's duration.

- `Disallow` rules are honoured for the configured user-agent, falling back to
  `*`.
- **`Crawl-delay` raises `crawl_delay_ms` if it is higher and never lowers
  it.** A site's stated delay is a floor.
- A 4xx on `/robots.txt` means no restrictions. A 5xx or a timeout means
  **treat the domain as disallowed for this run** — failing closed is correct
  when the site cannot tell you its rules.
- `respect_robots = false` is an operator override, logged every time it takes
  effect.

## 6. The three pools (ADR-0003)

One worker process, three `asyncio.TaskGroup` loops over one connection pool.

| Pool | Default size | Per-host | Gate |
| --- | --- | --- | --- |
| Static pages | 12 | 1 concurrent, 2 s gap | Postgres (§1) |
| Rendered pages | 3 in flight | 1 concurrent, same gate | Postgres (§1) |
| Assets | 24 | `asset_concurrency` (default 5), 200 ms gap | in-process semaphore |

A rendered fetch claims the **same** per-domain lock as a static one. Only
pool sizing differs; the scheduler neither knows nor cares which adapter ran.

**Browser contexts no longer live in this process** (ADR-0016). The rendered
pool is now a bounded set of concurrent HTTP calls to the render sidecar
(spec 012), which owns context pooling, recycling and its own hard cap. The
worker-side limit exists to avoid queueing at the sidecar, not to manage
browsers — keep it at or just below `RENDER_CONTEXTS`.

A 503 from the sidecar means its queue is full: treat it as backpressure,
return the row to `pending`, and try another domain. It is not a fetch
failure and must not increment `consecutive_failures`.

```python
class AssetGate:
    """Per-host concurrency for asset fetches.

    In-process on purpose: for assets the limit is a throughput knob, not a
    correctness property, so it is not worth a database round-trip per image.
    Two worker replicas each allowing 5 means a true limit of 10 — accepted,
    and documented in ADR-0003.
    """
    def __init__(self, per_host: int = 5, min_gap_ms: int = 200) -> None:
        self._sem: dict[str, asyncio.Semaphore] = {}
        self._next_ok: dict[str, float] = {}
        self._per_host, self._gap = per_host, min_gap_ms / 1000

    @asynccontextmanager
    async def acquire(self, host: str) -> AsyncIterator[None]:
        sem = self._sem.setdefault(host, asyncio.Semaphore(self._per_host))
        async with sem:
            wait = self._next_ok.get(host, 0.0) - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._next_ok[host] = time.monotonic() + self._gap
            yield
```

Context recycling, the hard cap and resource blocking are all properties of
the browser and therefore belong to the sidecar, not here. See spec 012 §2.

## 7. Backpressure

If `asset_queue` pending count exceeds **10,000**, page workers sleep 500 ms
between claims until it drops below 8,000. Without this a fast crawl over an
image-heavy catalogue builds a queue that outlives the run by hours.

The current depth is emitted on every progress event — it is the signal the
run monitor surfaces, and it belongs on screen rather than in a log.

## 8. Throughput expectations

Page throughput is `min(workers, eligible_domains)`. With 2–3 domains active
during onboarding you will see 2–3 concurrent page fetches no matter how many
workers run. **That ceiling is the politeness requirement, not a bug**, and
the UI should not imply otherwise.

The asset pool is where parallelism pays: images are 70–80% of bytes and one
product page can yield six.

## 9. Acceptance

- [ ] Two workers against one active domain never fetch concurrently
      (integration test, real Postgres, asserts on observed fetch timestamps).
- [ ] Two workers against four active domains reach four concurrent fetches.
- [ ] A killed worker's leased row returns to `pending` after `locked_until`
      and `in_flight` is reconciled.
- [ ] Three consecutive 403s pause the domain and abandon its queue rows.
- [ ] A `Crawl-delay: 10` in robots.txt raises an configured 2 s delay to
      10 s; a `Crawl-delay: 1` does not lower it.
- [ ] A 5xx on robots.txt causes the domain to be skipped for that run.
- [ ] Inter-request gaps for one host show jitter, not a constant.
- [ ] Asset queue above threshold measurably slows page claiming.
