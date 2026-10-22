"""`python -m spydra.worker`: the crawler (BUILD_PLAN 1.13, spec 002 §6).

Configuration is the environment compose already sets (`x-py-env`), plus the
pool sizes:

| Variable           | Default | Meaning                                         |
| ------------------ | ------- | ----------------------------------------------- |
| `DATABASE_URL`     | —       | the `crawl` schema's owner role                 |
| `USER_AGENT`       | —       | ADR-0004's honest identification; required      |
| `RENDER_BASE_URL`  | —       | the sidecar, through the host (ADR-0023)        |
| `WORKER_STATIC`    | 12      | static-pool claim loops (spec 002 §6)           |
| `WORKER_RENDERED`  | 3       | rendered-pool loops, and the sidecar budget     |
| `SHUTDOWN_GRACE_S` | 20      | how long in-flight pages get after SIGTERM      |
| `LOG_LEVEL`        | info    | spec 009 §1                                     |

**No asset pool yet.** ADR-0003's third pool drains `asset_queue`, and
nothing drains it until `5.2`, which brings the pool with its consumer.
"""

import asyncio
import os
import signal

import structlog
from sqlalchemy.ext.asyncio import create_async_engine

from spydra import logs
from spydra.adapters.clock import SystemClock
from spydra.adapters.http.auto_fetcher import AutoFetcher
from spydra.adapters.http.httpx_fetcher import HttpxFetcher
from spydra.adapters.http.render_service_fetcher import RenderServiceFetcher
from spydra.adapters.postgres.assets import PostgresAssets
from spydra.adapters.postgres.domains import PostgresDomains
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.observations import PostgresObservations
from spydra.adapters.postgres.pages import PostgresPages
from spydra.adapters.postgres.runs import PostgresRuns
from spydra.adapters.postgres.templates import PostgresTemplates
from spydra.extraction import ExtractionChain, SelectorStrategy, StructuredStrategy
from spydra.observations.writer import ObservationWriter
from spydra.scheduler.asset_pressure import AssetPressure
from spydra.scheduler.crawl import Fetchers, PageCrawler, Repositories
from spydra.scheduler.politeness import PolitenessGate
from spydra.scheduler.pools import RENDERED_MODES, STATIC_MODES, ClaimLoop, Pool, Worker
from spydra.scheduler.render_budget import RenderBudget
from spydra.scheduler.robots import RobotsCache

log = structlog.get_logger(__name__)


async def main() -> None:
    logs.configure(os.environ.get("LOG_LEVEL", "info"))
    static_size = int(os.environ.get("WORKER_STATIC", "12"))
    rendered_size = int(os.environ.get("WORKER_RENDERED", "3"))
    grace_s = float(os.environ.get("SHUTDOWN_GRACE_S", "20"))

    # One engine, so one connection pool for every loop (ADR-0003). Sized
    # for every loop holding a connection at once, plus the writer's.
    engine = create_async_engine(
        os.environ["DATABASE_URL"], pool_size=static_size + rendered_size + 2
    )
    clock = SystemClock()
    static = HttpxFetcher(clock)
    rendered = RenderBudget(
        RenderServiceFetcher(os.environ["RENDER_BASE_URL"], clock), rendered_size
    )
    observations = PostgresObservations(engine)
    runs = PostgresRuns(engine)
    assets = PostgresAssets(engine)
    frontier = PostgresFrontier(engine)
    crawler = PageCrawler(
        frontier=frontier,
        repositories=Repositories(
            domains=PostgresDomains(engine),
            pages=PostgresPages(engine),
            templates=PostgresTemplates(engine),
            observations=observations,
            runs=runs,
        ),
        writer=ObservationWriter(observations, assets),
        chain=ExtractionChain([StructuredStrategy(), SelectorStrategy()]),
        gate=PolitenessGate(clock),
        robots=RobotsCache(static),
        fetchers=Fetchers(static=static, rendered=rendered, auto=AutoFetcher(static, rendered)),
        user_agent=os.environ["USER_AGENT"],
        clock=clock,
    )
    pressure = AssetPressure()
    pools = (
        Pool("static", static_size, STATIC_MODES),
        Pool("rendered", rendered_size, RENDERED_MODES),
    )
    worker = Worker(
        [
            ClaimLoop(
                pool=pool,
                frontier=frontier,
                assets=assets,
                runs=runs,
                pressure=pressure,
                crawler=crawler,
            )
            for pool in pools
            for _ in range(pool.size)
        ],
        grace_s=grace_s,
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, worker.stop.set)

    log.info("worker_started", static=static_size, rendered=rendered_size)
    try:
        await worker.run()
    finally:
        await static.aclose()
        await rendered.aclose()
        await engine.dispose()
        log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
