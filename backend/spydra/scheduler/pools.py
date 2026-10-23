"""The claim loops and the pools they run in (spec 002 §1–§7, ADR-0003).

```
iteration:  sweep expired leases  →  asset backpressure  →  claim  →  crawl
                (spec 002 §3)            (spec 002 §7)       (§1)
```

**A `None` claim means "nothing claimable now", never "the frontier is
empty"**, so the loop idles and goes round again. Politeness makes most
claims come back empty: with two domains onboarding, throughput is two pages
per crawl delay however many loops run (spec 002 §8). A loop that exited on
`None` would end the crawl the first time every domain was waiting out its
delay. The worker runs until it is told to stop.

**The sweep runs every iteration**, as spec 002 §3 says, and since ADR-0026 it
is load-bearing: a worker killed mid-page leaves its domain's `in_flight`
high, and nothing else lowers it.

**Shutdown** (SIGTERM, `docker compose stop`): no new claim starts, and a
claim that raced the signal is released unfetched; pages
already being crawled get `grace_s` to finish; whatever remains is cancelled
and its row released with no penalty, so the next worker picks it straight up
rather than after a two-minute lease.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from spydra.adapters.postgres.assets import PostgresAssets
from spydra.adapters.postgres.run_events import PostgresRunEvents
from spydra.adapters.postgres.runs import PostgresRuns
from spydra.domain.enums import RenderMode
from spydra.ports.frontier import ClaimedUrl, Frontier
from spydra.scheduler.asset_pressure import AssetPressure
from spydra.scheduler.crawl import PageCrawler

log = structlog.get_logger(__name__)

IDLE_S = 0.5
# After a row went back unfetched because the sidecar was full or down: the
# same domain is still the most eligible, so claiming again at once is a
# claim/release cycle at hundreds a second (found in review).
BACKPRESSURE_S = 2.0
CLAIM_FAILED_EVERY = 30
# After an unexpected error in the loop itself (the database went away): long
# enough not to spin, short enough that a restarted database is picked up.
ERROR_BACKOFF_S = 2.0


@dataclass(frozen=True, slots=True)
class Pool:
    """A named set of claim loops over the domains of some render modes."""

    name: str
    size: int
    render_modes: frozenset[RenderMode]


STATIC_MODES = frozenset({RenderMode.STATIC, RenderMode.AUTO})
RENDERED_MODES = frozenset({RenderMode.RENDERED})


class ClaimLoop:
    def __init__(
        self,
        *,
        pool: Pool,
        frontier: Frontier,
        assets: PostgresAssets,
        runs: PostgresRuns,
        events: PostgresRunEvents,
        pressure: AssetPressure,
        crawler: PageCrawler,
    ) -> None:
        self._pool = pool
        self._frontier = frontier
        self._assets = assets
        self._runs = runs
        self._events = events
        self._pressure = pressure
        self._crawler = crawler
        self._failures = 0

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                item = await self._next()
            except Exception:
                self._claim_failed()
                await _sleep_unless(stop, ERROR_BACKOFF_S)
                continue
            self._failures = 0
            if item is None:
                await _sleep_unless(stop, IDLE_S)
                continue
            if stop.is_set():
                # The claim raced the signal. Nothing has been fetched, so the
                # row goes straight back rather than starting a request after
                # SIGTERM.
                await self._frontier.release(item)
                return
            if await self._crawl(item):
                await _sleep_unless(stop, BACKPRESSURE_S)

    async def _next(self) -> ClaimedUrl | None:
        if await self._frontier.sweep_expired_leases():
            # A row the sweep retired is closed by no worker, so if it was a
            # run's last one the run is finished here or never.
            for run_id, stats in await self._runs.finish_drained():
                log.info("run_finished", run_id=int(run_id), stats=stats)
        # The maintenance beat's other half (ADR-0042): keep the last 5,000
        # events per live run. Probes, not scans — a run under the bound
        # deletes nothing.
        await self._events.trim()
        await self._pressure.before_claim(await self._assets.pending())
        return await self._frontier.claim(self._pool.render_modes)

    def _claim_failed(self) -> None:
        """The database (or the loop itself) failed. Logged with a traceback
        the first time and then once per `CLAIM_FAILED_EVERY` attempts: 15
        loops retrying every 2 s through an outage would otherwise be ~450
        error lines a minute (spec 009 §5)."""
        self._failures += 1
        if self._failures == 1 or self._failures % CLAIM_FAILED_EVERY == 0:
            log.error(
                "claim_failed",
                pool=self._pool.name,
                consecutive=self._failures,
                exc_info=self._failures == 1,
                action="check that the database is reachable; the worker retries by itself",
            )

    async def _crawl(self, item: ClaimedUrl) -> bool:
        """`True` asks the loop to back off before claiming again."""
        # `domain_id` here; the crawler binds `domain` (the host) once it has
        # read the row, so `domain` is always the same type in every line.
        with structlog.contextvars.bound_contextvars(
            run_id=int(item.run_id),
            domain_id=int(item.domain_id),
            url=item.url,
            attempt=item.attempts,
            pool=self._pool.name,
        ):
            try:
                return await self._crawler.crawl(item)
            except asyncio.CancelledError:
                await self._release_on_shutdown(item)
                raise
            except Exception:
                log.exception("crawl_crashed", action="a crawler bug: read the traceback")
                try:
                    await self._crawler.abort(item)
                except asyncio.CancelledError:
                    # Cancelled inside the handler: the sibling clause above
                    # does not see it, so the release happens here too.
                    await self._release_on_shutdown(item)
                    raise
                except Exception:
                    # The lease sweep is the backstop: the row comes back
                    # after `locked_until` and `in_flight` is reconciled.
                    log.exception("abort_failed", action="none; the lease sweep recovers the row")
                return False
            finally:
                structlog.contextvars.unbind_contextvars("strategy", "domain")

    async def _release_on_shutdown(self, item: ClaimedUrl) -> None:
        """Shutdown overran the grace. The row goes back with no penalty,
        shielded so the cancellation cannot interrupt the release itself and
        strand the domain's `in_flight`. Fenced on the lease, so a row this
        claim already closed is left closed."""
        if await asyncio.shield(self._frontier.release(item)):
            log.info("released_on_shutdown")


class Worker:
    """The pools, in one `TaskGroup` over one engine (ADR-0003)."""

    def __init__(self, loops: Sequence[ClaimLoop], *, grace_s: float) -> None:
        self._loops = tuple(loops)
        self._grace_s = grace_s
        self.stop = asyncio.Event()

    async def run(self) -> None:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(loop.run(self.stop)) for loop in self._loops]
            group.create_task(self._enforce_grace(tasks))

    async def _enforce_grace(self, tasks: list[asyncio.Task[None]]) -> None:
        await self.stop.wait()
        _, overran = await asyncio.wait(tasks, timeout=self._grace_s)
        if overran:
            log.warning("shutdown_grace_exceeded", cancelling=len(overran))
        for task in overran:
            task.cancel()


async def _sleep_unless(stop: asyncio.Event, seconds: float) -> None:
    """Sleep, but wake at once on shutdown, so an idle worker stops in
    milliseconds rather than at the end of its nap."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
