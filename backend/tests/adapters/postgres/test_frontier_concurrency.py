"""The politeness guarantee, with real workers on real connections (1.8).

**This is the test the system exists to pass.** TESTING.md §2 puts it first,
and ADR-0026 exists because the query spec 002 §1 originally specified failed
it in **twenty rounds out of twenty** on real Postgres while raising no
error.

So it is written the way that ADR and TESTING.md §2 both demand, and every
part of that is load-bearing:

- **Two separate engines**, so two separate connections. One connection
  cannot race itself, and `SKIP LOCKED` is invisible within a transaction.
- **No rolled-back fixture.** `conftest.py`'s `conn` would hide the whole
  thing: two workers cannot see each other's uncommitted work, so the lock
  would never be contended and the test would pass against the broken query.
- **Assertions on observed timestamps**, not on mocks or on a counter. The
  guarantee is about when requests leave this machine.
- **Many rounds.** A single round passes against the racy query most of the
  time; the ADR measured 20/20 failures only by running it 20 times.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.ports.frontier import ClaimedUrl, Completion, QueueItemState
from tests.adapters.postgres.seed import domain_row, seed_domain, seed_queue_row, seed_run

pytestmark = pytest.mark.integration

# Long enough that an overlap would be observed rather than inferred from
# two timestamps a microsecond apart, short enough to keep the suite usable.
FETCH_MS = 40

# The ADR measured the broken query failing 20/20. Fewer rounds here would be
# a weaker test than the one that found the bug.
ROUNDS = 20


# A short polite delay after each fetch. NOT zero, and that is the whole
# reason this constant has a comment.
#
# The first version of this harness completed with `next_eligible_at` already
# in the past, so the domain was instantly eligible again. The worker that
# had just finished looped straight back into `claim()` with no await in
# between, while the other was sleeping off a missed poll — and it won every
# round. The anti-vacuity control below caught it: **one worker did all 20
# rounds**, so "the two fetch windows never overlapped" was true because
# there was only ever one worker fetching.
#
# A real worker always has this delay (spec 002 §2 advances
# `next_eligible_at` by `crawl_delay_ms × jitter`), so removing it to "keep
# the test focused on concurrency" removed the thing that makes two workers
# contend in the first place.
POLITE_MS = 15


def completion(state: QueueItemState = QueueItemState.DONE) -> Completion:
    """No politeness arithmetic: the gate (1.9) computes these values."""
    return Completion(
        state=state,
        next_eligible_at=datetime.now(UTC) + timedelta(milliseconds=POLITE_MS),
        crawl_delay_ms=2000,
        consecutive_failures=0,
    )


async def worker(
    name: str,
    url: str,
    target: int,
    log: list[tuple[str, str, datetime, datetime]],
    deadline: datetime,
) -> None:
    """One worker on its OWN engine, claiming until the queue is drained.

    Driven by the shared log reaching `target` rather than by a fixed
    iteration count. The first version counted iterations, and with a polite
    delay between rounds the two workers burned their budget on missed polls
    and stopped with the queue half full — which failed as "expected every
    row fetched exactly once" and looks like a frontier bug rather than a
    harness one. The deadline is the backstop so a genuine stall fails the
    test instead of hanging it.

    The engine is created inside the coroutine so each worker genuinely has
    its own pool. Sharing an engine would share a pool, and two tasks taking
    two connections from one pool is close enough to the real thing to be
    tempting and far enough to be worth not relying on.
    """
    engine = create_async_engine(url)
    frontier = PostgresFrontier(engine)
    try:
        while len(log) < target and datetime.now(UTC) < deadline:
            claimed: ClaimedUrl | None = await frontier.claim()
            if claimed is None:
                await asyncio.sleep(0.002)
                continue
            # The "fetch". The window between claim and complete is exactly
            # the window in which the domain must not be fetched again.
            started = datetime.now(UTC)
            await asyncio.sleep(FETCH_MS / 1000)
            finished = datetime.now(UTC)
            log.append((name, claimed.url, started, finished))
            await frontier.complete(claimed, completion())
            # Yield before racing for the next row. Without it the worker
            # that just completed re-enters `claim()` in the same scheduler
            # slot and starves the other one — see POLITE_MS.
            await asyncio.sleep(0)
    finally:
        await engine.dispose()


def overlaps(log: list[tuple[str, str, datetime, datetime]]) -> list[tuple[str, str]]:
    """Every pair of fetch windows that were open at the same time."""
    found: list[tuple[str, str]] = []
    ordered = sorted(log, key=lambda entry: entry[2])
    for i, (_, url_a, _start_a, end_a) in enumerate(ordered):
        for _, url_b, start_b, _end_b in ordered[i + 1 :]:
            if start_b >= end_a:
                break
            found.append((url_a, url_b))
    return found


# ---------------------------------------------------------------------------
# E4 — the guarantee
# ---------------------------------------------------------------------------


async def test_two_workers_never_fetch_one_domain_concurrently(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """The first line of TESTING.md §2, and the reason ADR-0026 exists.

    With `max_concurrency = 1`, the two fetch windows must never overlap. The
    original query — `FOR UPDATE SKIP LOCKED` on `crawl_queue` only — handed
    two workers two different rows OF THE SAME DOMAIN, because neither had
    committed its `in_flight` increment and both read the domain as eligible.
    Two simultaneous connections to one host, arrived at through the
    mechanism meant to prevent it, with nothing raised.
    """
    engine = clean_crawl
    domain = await seed_domain(engine, max_concurrency=1)
    run = await seed_run(engine, [int(domain)])
    for i in range(ROUNDS):
        await seed_queue_row(engine, run, domain, f"https://v.test/p{i}")

    log: list[tuple[str, str, datetime, datetime]] = []
    deadline = datetime.now(UTC) + timedelta(seconds=30)
    await asyncio.gather(
        worker("a", database_url, ROUNDS, log, deadline),
        worker("b", database_url, ROUNDS, log, deadline),
    )

    assert len(log) == ROUNDS, f"expected every row fetched exactly once, got {len(log)}"
    assert len({entry[1] for entry in log}) == ROUNDS, "a URL was fetched twice"

    # Anti-vacuity control. "Never concurrent" is trivially true of a
    # frontier that only ever lets ONE worker claim anything, so this
    # asserts both workers really competed and both got work. Without it,
    # a claim that starved the second worker entirely would pass the
    # overlap assertion perfectly.
    by_worker = {name for name, _, _, _ in log}
    assert by_worker == {"a", "b"}, (
        f"only {by_worker} did any work, so the no-overlap assertion above may be "
        "passing because one worker was starved rather than because the gate held"
    )

    collisions = overlaps(log)
    assert not collisions, (
        f"{len(collisions)} overlapping fetch windows against one domain with "
        f"max_concurrency=1 — the politeness guarantee is broken. Read ADR-0026: "
        f"this is what happens when the claim does not lock the domain row. "
        f"First few: {collisions[:3]}"
    )
    assert (await domain_row(engine, domain)).in_flight == 0


# ---------------------------------------------------------------------------
# E5 — and it must not serialise work it is not meant to
# ---------------------------------------------------------------------------


async def test_four_eligible_domains_reach_four_concurrent_claims(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """The other half, and the half a too-eager fix would break. `SKIP LOCKED`
    on `domains` exists so a worker **skips** a domain someone else is
    deciding about and takes the next eligible one; plain `FOR UPDATE` would
    make it wait, and four domains would then be crawled one at a time.

    Throughput is `min(workers, eligible_domains)` (spec 002 §8), so this
    asserts four claims held **at once** rather than four claims eventually.

    Note: TESTING.md §2 words this as "two workers, four domains → four
    concurrent", which cannot be literally true — two workers cannot hold
    four claims. Four claimers against four domains is the assertion that
    carries the intent, and the wording is raised in the task file.
    """
    engine = clean_crawl
    domains = [await seed_domain(engine, host=f"host{i}.test", max_concurrency=1) for i in range(4)]
    run = await seed_run(engine, [int(d) for d in domains])
    for i, domain in enumerate(domains):
        await seed_queue_row(engine, run, domain, f"https://host{i}.test/a")

    engines = [create_async_engine(database_url) for _ in range(4)]
    try:
        claims = await asyncio.gather(*(PostgresFrontier(e).claim() for e in engines))
    finally:
        for e in engines:
            await e.dispose()

    held = [c for c in claims if c is not None]
    assert len(held) == 4, (
        f"only {len(held)} of 4 eligible domains were claimed concurrently — the "
        "gate is serialising across domains, which is what plain FOR UPDATE "
        "instead of SKIP LOCKED would do"
    )
    assert len({int(c.domain_id) for c in held}) == 4, "two claims came from one domain"
    for domain in domains:
        assert (await domain_row(engine, domain)).in_flight == 1


async def test_concurrent_claims_never_exceed_max_concurrency_and_can_reach_it(
    clean_crawl: AsyncEngine, database_url: str
) -> None:
    """The control for the first test, and a measured note about ADR-0026.

    **The control.** "The two fetch windows never overlapped" is trivially
    true of a frontier that only ever lets one claim succeed, so something
    has to prove `max_concurrency` is reachable at all. Otherwise the test
    above passes against a gate that is simply stuck shut.

    **The note.** `FOR UPDATE SKIP LOCKED` on `crawl.domains` serialises the
    eligibility decision, so when two claim transactions genuinely overlap on
    one domain, the second finds the row locked and **skips a domain it was
    entitled to use** — capacity was 2. ADR-0026 justifies `SKIP LOCKED` over
    plain `FOR UPDATE` on the grounds that "blocking would make a worker wait
    for a domain it is not allowed to fetch from anyway", which is true at
    `max_concurrency = 1` and not above it.

    That costs correctness nothing (erring toward fewer concurrent fetches is
    the safe direction) and throughput almost nothing (the claim transaction
    is microseconds and the loser wins on its next attempt). It is raised in
    the task file as an ADR-0026 addendum rather than treated as a defect.

    **Whether the two overlap is not asserted, because it is not
    deterministic.** `asyncio.gather` starts both coroutines but the first
    can finish its whole transaction before the second reaches the database,
    in which case both succeed. Measured flaky across three consecutive runs
    — one run saw two claims, two runs saw one. So the assertions are the two
    things that are invariant: never more than capacity, and capacity is
    reachable.
    """
    engine = clean_crawl
    domain = await seed_domain(engine, max_concurrency=2)
    run = await seed_run(engine, [int(domain)])
    for i in range(3):
        await seed_queue_row(engine, run, domain, f"https://v.test/{i}")

    engines = [create_async_engine(database_url) for _ in range(2)]
    try:
        simultaneous = await asyncio.gather(*(PostgresFrontier(e).claim() for e in engines))
        held = [c for c in simultaneous if c is not None]
        assert 1 <= len(held) <= 2, f"{len(held)} claims from two attempts"

        # Capacity is reachable: whatever the first pass did, claiming again
        # fills the domain to max_concurrency and then stops.
        while True:
            extra = await PostgresFrontier(engines[0]).claim()
            if extra is None:
                break
            held.append(extra)

        assert len(held) == 2, (
            f"max_concurrency=2 yielded {len(held)} concurrent claims. Below 2 and "
            "the setting is a lie and the no-overlap test above may be passing "
            "against a gate stuck shut; above 2 and the gate is not a gate"
        )
    finally:
        for e in engines:
            await e.dispose()

    assert (await domain_row(engine, domain)).in_flight == 2
