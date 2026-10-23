"""The run lifecycle through the real worker (BUILD_PLAN 2.7, ADR-0041).

**The operator's three verbs at crawl size.** The adapter's guarded
predicates are pinned in `tests/adapters/postgres/test_run_lifecycle.py`;
what only the subprocess can prove is the other half of every mechanism:
that a running worker — claiming, fetching, closing rows — cooperates with
each transition without a single line of scheduler code changing
(`backend/spydra/scheduler/` is untouched by design, and these tests are
why that is a property rather than an omission).

- **Stop mid-crawl**: pending rows abandoned and reported, the in-flight
  tail finishes and closes `done` without completing the run, the worker
  drains to idle without resurrecting it, and a row released after the
  stop (SIGTERM cancelling a fetch the operator had already stopped)
  lands `abandoned`, never `pending`.
- **Pause**: claiming stops while every row stays `pending` (none
  abandoned, no reason), and the in-flight tail's discovery still
  enqueues — pause freezes dequeue, not discovery.
- **Resume**: the crawl completes; a run that drained while paused is
  completed by the resume itself, not left hanging `running`.

All on the `seed_halden` substrate (one connection, per-domain gate,
20 ms delay) or, where a fetch must be slow enough to interrupt, the
worker-process harness's own slow fixture pages.
"""

import asyncio
from pathlib import Path
from subprocess import Popen

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.clock import SystemClock
from spydra.adapters.http.httpx_fetcher import HttpxFetcher
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.runs import PostgresRuns
from tests.fixtures.server import FixtureSite
from tests.scheduler.test_canonical_pages import build, make_due
from tests.scheduler.test_dedupe_recrawl import wait_completed
from tests.scheduler.test_link_discovery import seed_halden
from tests.scheduler.test_worker_process import (
    rows,
    run_state,
    seed_site,
    sigterm,
    wait_until,
    worker,
)

pytestmark = pytest.mark.integration


# The fixture records robots.txt requests too; only /shop/ paths are the
# crawl's own work on the Halden substrate.
def crawl_requests(site: FixtureSite) -> list[str]:
    return [p for _, p in site.requests if p.startswith("/shop/")]


async def queue_states(engine: AsyncEngine, run: int) -> list[str]:
    return [
        r.state
        for r in await rows(engine, "SELECT state FROM crawl.crawl_queue WHERE run_id = :r", r=run)
    ]


async def nothing_in_flight(engine: AsyncEngine, run: int) -> bool:
    return not await rows(
        engine,
        "SELECT 1 FROM crawl.crawl_queue WHERE run_id = :r AND state = 'in_flight'",
        r=run,
    )


async def requests_frozen_for(
    site: FixtureSite, proc: Popen[bytes], log: Path, *, seconds: float
) -> int:
    """The count of crawled requests after a window in which none arrived.

    A worker whose claims had kept flowing would fetch a page every few
    tens of milliseconds at the substrate's delay, so a frozen count over
    a window this wide is a stopped dequeue, not a slow one."""
    at_pause = len(crawl_requests(site))
    await asyncio.sleep(seconds)

    async def still_frozen() -> bool:
        return len(crawl_requests(site)) == at_pause

    await wait_until(still_frozen, proc, log, timeout=5, what="requests to stay frozen")
    return at_pause


# ---------------------------------------------------------------------------
# 1. Stop, mid-crawl
# ---------------------------------------------------------------------------


async def test_a_run_stopped_mid_crawl_reports_the_work_it_did_not_do(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """The operator's stop against a live crawl. Everything stop promises
    is observable here and nowhere else: the pending rows turn `abandoned`
    and the run's stats carry that number exactly (ADR-0040's ordering),
    the in-flight row finishes its fetch and closes `done` WITHOUT its
    finish completing the run (the finish fences on `running`), the
    domain stays `active`, and the worker — still running — claims
    nothing more for that run, for ever."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        base = site.base_url
        domain, run, _ = await seed_halden(engine, base)
        with worker(database_url, log, WORKER_STATIC="1") as proc:

            async def two_pages_crawled() -> bool:
                return len(crawl_requests(site)) >= 2

            await wait_until(
                two_pages_crawled, proc, log, timeout=60, what="the crawl to be under way"
            )

            stop = await PostgresRuns(engine).stop_run(run)
            assert stop.transitioned, "the run finished before the stop landed"
            assert stop.abandoned > 0

            # The in-flight tail drains, the worker stays up, and the run
            # is neither completed by the tail's finish nor resurrected.
            await wait_until(
                lambda: nothing_in_flight(engine, int(run)),
                proc,
                log,
                timeout=30,
                what="the in-flight tail to finish after the stop",
            )
            await requests_frozen_for(site, proc, log, seconds=0.8)
            assert await run_state(engine, run) == "stopped"
            proc.terminate()
            proc.wait(timeout=30)

        requested = set(crawl_requests(site))

    states = await queue_states(engine, int(run))
    assert "pending" not in states, "stop left work the run would wait on for ever"
    assert "abandoned" in states and "done" in states

    finished = (
        await rows(
            engine,
            "SELECT state::text AS s, stop_reason, finished_at, stats"
            " FROM crawl.runs WHERE id = :r",
            r=int(run),
        )
    )[0]

    # Never a clean finish and never a silent one: terminal `stopped`, the
    # operator named, and the work-not-done number exact at stop time.
    assert finished.s == "stopped"
    # The vocabulary is spec 001 §2's, pinned as a literal.
    assert finished.stop_reason == "stopped by operator"
    assert finished.finished_at is not None
    assert finished.stats["pages_abandoned"] == states.count("abandoned")
    assert finished.stats["pages_abandoned"] > 0

    # The in-flight tail finished its fetch: pages were observed, and the
    # snapshot's `pages_crawled` may legitimately trail the tail's late
    # closes (ADR-0041's stated, bounded cost).
    observed = await rows(
        engine,
        "SELECT count(*) AS n FROM crawl.page_observations WHERE run_id = :r",
        r=int(run),
    )
    assert observed[0].n >= 1, "no page the crawl had reached was observed"
    assert finished.stats["pages_crawled"] >= 1
    assert finished.stats["pages_crawled"] <= states.count("done")

    # Nothing was fetched after the stop: every request the site saw is a
    # page that closed `done` — a post-stop fetch of stopped work would
    # make the requested set larger than the done count.
    assert len(requested) == states.count("done"), (
        f"{len(requested)} pages requested but {states.count('done')} closed done: "
        "work the operator stopped was still fetched"
    )
    assert await run_state(engine, run) == "stopped"

    # Run-scoped, not a domain state: the domain is untouched and stays
    # claimable for the next run.
    assert (
        await rows(
            engine, "SELECT state::text AS s FROM crawl.domains WHERE id = :d", d=int(domain)
        )
    )[0].s == "active"


async def test_a_row_cancelled_after_stop_is_released_abandoned(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """The release path's terminal routing, driven the way it happens: the
    operator stops the run while a 15 s page is mid-fetch, then SIGTERMs
    the worker inside a 1 s grace. The cancelled fetch's row must be
    released `abandoned` — back to `pending` it would sit on a stopped run
    unclaimable and unreported, and the run would carry a hole in its
    work-not-done number for ever."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    paths = ["/slow/15000/a", "/generated/1", "/generated/2"]
    with FixtureSite() as site:
        _, run = await seed_site(engine, site.base_url, paths)
        with worker(database_url, log, WORKER_STATIC="1", SHUTDOWN_GRACE_S="1") as proc:

            async def slow_page_in_flight() -> bool:
                return any(p.startswith("/slow/") for _, p in site.requests)

            # Bread-first by (depth, id): the slow row is claimed first, so
            # the two fast rows are still pending when the stop lands.
            await wait_until(
                slow_page_in_flight, proc, log, timeout=30, what="the slow page in flight"
            )

            stop = await PostgresRuns(engine).stop_run(run)
            assert stop.transitioned and stop.abandoned == 2

            code, _ = sigterm(proc, timeout=15)

    assert code == 0, log.read_text()[-4000:]
    states = await queue_states(engine, int(run))
    assert states == ["abandoned"] * 3, (
        f"the cancelled fetch's row went back to {states[0]!r} on a stopped run"
    )
    finished = (
        await rows(
            engine, "SELECT state::text AS s, stats FROM crawl.runs WHERE id = :r", r=int(run)
        )
    )[0]
    assert finished.s == "stopped"
    # The snapshot is exact AT STOP: the two pending rows. The cancelled
    # fetch's row is part of the in-flight tail — abandoned in the queue by
    # the release's routing (the assertion above), not recounted in the
    # stop-time stats. That is ADR-0041's stated, bounded snapshot cost,
    # the same one the tail's `done` closes pay on `pages_crawled`.
    assert finished.stats["pages_abandoned"] == 2


# ---------------------------------------------------------------------------
# 2. Pause — dequeue frozen, discovery not
# ---------------------------------------------------------------------------


async def test_pause_freezes_claiming_keeps_every_row_and_resume_completes(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """Pause against the live crawl: claiming stops (requests freeze while
    the worker stays up), every row stays `pending` — none abandoned, no
    `stop_reason`, because pause is not terminal — and resume returns the
    run to `running` and it crawls to `completed` with stats."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        base = site.base_url
        domain, run, _ = await seed_halden(engine, base)
        with worker(database_url, log, WORKER_STATIC="1") as proc:

            async def two_pages_crawled() -> bool:
                return len(crawl_requests(site)) >= 2

            await wait_until(
                two_pages_crawled, proc, log, timeout=60, what="the crawl to be under way"
            )

            paused = await PostgresRuns(engine).pause_run(run)
            assert paused.transitioned, "the run finished before the pause landed"

            await wait_until(
                lambda: nothing_in_flight(engine, int(run)),
                proc,
                log,
                timeout=30,
                what="the in-flight tail to finish under pause",
            )
            await requests_frozen_for(site, proc, log, seconds=0.8)

            row = (
                await rows(
                    engine,
                    "SELECT state::text AS s, stop_reason FROM crawl.runs WHERE id = :r",
                    r=int(run),
                )
            )[0]
            states = await queue_states(engine, int(run))
            assert row.s == "paused"
            assert row.stop_reason is None
            assert "abandoned" not in states, "pause abandoned work; pause is not stop"
            assert states.count("pending") > 0, "the crawl had already drained"
            # The tail's discovery enqueued while paused: the queue grew
            # past the pages actually crawled.
            assert states.count("done") < len(states)

            resumed = await PostgresRuns(engine).resume_run(run)
            assert resumed.transitioned
            assert resumed.stats is None, "work remained; resume must not complete the run"
            await wait_completed(engine, proc, log, run, what="the resumed crawl")
            proc.terminate()
            proc.wait(timeout=30)

    assert await run_state(engine, run) == "completed"
    assert set(await queue_states(engine, int(run))) == {"done"}
    finished = (
        await rows(engine, "SELECT stats, stop_reason FROM crawl.runs WHERE id = :r", r=int(run))
    )[0]
    assert finished.stats["pages_abandoned"] == 0
    assert finished.stats["pages_crawled"] == len(await queue_states(engine, int(run)))
    assert finished.stop_reason is None
    assert (
        await rows(
            engine, "SELECT state::text AS s FROM crawl.domains WHERE id = :d", d=int(domain)
        )
    )[0].s == "active"


async def test_the_in_flight_tail_of_a_paused_run_closes_done_and_discovers(
    clean_crawl: AsyncEngine,
) -> None:
    """Pause mid-fetch, deterministically: the seed listing is claimed,
    THEN the run is paused, and only then does the page crawl. Its row
    must close `done`, its observation must be written, and — the widened
    `_ENQUEUE` fence — its discovered links must land `pending` under the
    paused run. The 2.3-era guard would have dropped every one of them,
    and resume would have produced a silently incomplete crawl."""
    engine = clean_crawl
    with FixtureSite() as site:
        base = site.base_url
        domain, run, _ = await seed_halden(engine, base)
        await make_due(engine, domain)
        frontier = PostgresFrontier(engine)
        item = await frontier.claim()
        assert item is not None, "the seed was not claimable"
        assert (await PostgresRuns(engine).pause_run(run)).transitioned

        static = HttpxFetcher(SystemClock())
        try:
            await build(engine, static).crawl(item)
        finally:
            await static.aclose()

    seeded_url = item.url
    queue = await rows(
        engine,
        "SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id",
        r=int(run),
    )
    by_url = {r.url: r.state for r in queue}
    assert by_url[seeded_url] == "done", "the in-flight row did not close normally"
    observed = await rows(
        engine,
        "SELECT count(*) AS n FROM crawl.page_observations WHERE run_id = :r",
        r=int(run),
    )
    assert observed[0].n == 1, "the tail's observation was not written"

    discovered = [u for u, s in by_url.items() if u != seeded_url]
    assert len(discovered) >= 3, "the paused tail's discovery was dropped"
    assert {s for u, s in by_url.items() if u != seeded_url} == {"pending"}
    row = (
        await rows(
            engine, "SELECT state::text AS s, stop_reason FROM crawl.runs WHERE id = :r", r=int(run)
        )
    )[0]
    assert (row.s, row.stop_reason) == ("paused", None)

    # And nothing of it is claimable until resume: the fence, not the queue.
    await make_due(engine, domain)
    assert await frontier.claim() is None, "a paused run's rows were claimed"


# ---------------------------------------------------------------------------
# 3. Resume — and the run that drained while paused
# ---------------------------------------------------------------------------


async def test_resume_completes_a_run_that_drained_while_paused(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """The run nothing else can close. A single slow page is the whole
    queue: pause lands while it is in flight, the page finishes and closes
    `done` — and the finish must refuse (the run is `paused`), leaving a
    drained, paused run that no worker will ever close again, because none
    of its rows will ever close again. Resume must complete it in the same
    transaction rather than leave it hanging `running`."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        _, run = await seed_site(engine, site.base_url, ["/slow/1500/only"])
        with worker(database_url, log, WORKER_STATIC="1") as proc:

            async def slow_page_in_flight() -> bool:
                return any(p.startswith("/slow/") for _, p in site.requests)

            await wait_until(
                slow_page_in_flight, proc, log, timeout=30, what="the slow page in flight"
            )
            paused = await PostgresRuns(engine).pause_run(run)
            assert paused.transitioned, (
                "the pause landed after the run had already completed; the slow "
                "page's window was missed"
            )

            async def tail_closed() -> bool:
                return await queue_states(engine, int(run)) == ["done"]

            await wait_until(tail_closed, proc, log, timeout=30, what="the in-flight tail to close")

            # The tail's own finish refused: the run is still `paused`,
            # holding a fully drained queue that nothing will close.
            assert await run_state(engine, run) == "paused"

            resumed = await PostgresRuns(engine).resume_run(run)
            assert resumed.transitioned
            assert resumed.stats is not None, (
                "resume left a drained run `running`; nothing will ever close it"
            )
            proc.terminate()
            proc.wait(timeout=30)

    assert await run_state(engine, run) == "completed"
    finished = (await rows(engine, "SELECT stats FROM crawl.runs WHERE id = :r", r=int(run)))[0]
    assert finished.stats["pages_crawled"] == 1
    assert finished.stats["pages_abandoned"] == 0
