"""Phase 1's exit criterion, checked against the live compose stack.

BUILD_PLAN 1.14: "the local fixture site crawled politely end to end from a
YAML template — a static page and a JavaScript-dependent page, both fetchers
exercised by the same scheduler, data in Postgres, and asset rows enqueued.
Stopping the `render` service leaves static crawling unaffected and makes
`auto` record `static_fallback`."

Not collected by pytest (no `test_` prefix): it needs the `phase1-exit`
profile's services, which only `make phase1-exit` brings up
(`scripts/phase1-exit.sh`). Run inside the api container against the TEST
database, so an exit run never writes the operator's dev data.

    python -m tests.phase1_exit reset
    python -m tests.phase1_exit render-up   <run_id>
    python -m tests.phase1_exit render-down <run_id>
"""

import asyncio
import os
import sys
import time
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

TIMEOUT_S = 180

_OBSERVED = sa.text(
    """
SELECT d.host, o.http_status, o.strategy, o.extraction_rung, o.title,
       o.price_amount, o.price_currency, o.empty_extraction
FROM crawl.page_observations o
JOIN crawl.pages p ON p.id = o.page_id
JOIN crawl.domains d ON d.id = p.domain_id
WHERE o.run_id = :run
"""
)


async def _wait_for_completion(engine: AsyncEngine, run: int) -> dict[str, Any]:
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        async with engine.connect() as conn:
            state, stats = (
                await conn.execute(
                    sa.text("SELECT state::text, stats FROM crawl.runs WHERE id = :r"), {"r": run}
                )
            ).one()
        if state == "completed":
            return dict(stats)
        await asyncio.sleep(1)
    raise SystemExit(f"run {run} did not complete within {TIMEOUT_S} s")


async def _by_host(engine: AsyncEngine, run: int) -> dict[str, sa.Row[Any]]:
    async with engine.connect() as conn:
        rows = (await conn.execute(_OBSERVED, {"run": run})).all()
    return {row.host.split(":")[0]: row for row in rows}


async def _assets(engine: AsyncEngine, run: int) -> int:
    async with engine.connect() as conn:
        return int(
            (
                await conn.execute(
                    sa.text("SELECT count(*) FROM crawl.asset_queue WHERE run_id = :r"),
                    {"r": run},
                )
            ).scalar_one()
        )


def _check(ok: bool, what: str, detail: object = "") -> None:
    print(f"  {'✓' if ok else '✗'} {what}" + (f"  ({detail})" if not ok else ""))
    if not ok:
        raise SystemExit(f"phase 1 exit failed: {what}")


async def render_up(engine: AsyncEngine, run: int) -> None:
    stats = await _wait_for_completion(engine, run)
    pages = await _by_host(engine, run)
    print(f"run {run} completed: {stats}")
    static, rendered, auto = (
        pages.get("vantage.fixtures"),
        pages.get("mertens.fixtures"),
        pages.get("orbis.fixtures"),
    )
    _check(
        static is not None and static.title == "Resin Fibre Disc 115mm P60",
        "static page extracted through HttpxFetcher",
        static,
    )
    _check(
        static is not None and static.price_currency == "GBP",
        "static price has its currency",
        static,
    )
    _check(
        rendered is not None and rendered.title == "Stirnlochschluessel 30-80mm",
        "JS-dependent page extracted through the render sidecar",
        rendered,
    )
    _check(
        auto is not None
        and auto.title == "Stirnlochschluessel 30-80mm"
        and auto.strategy != "static_fallback",
        "AUTO page rendered by its second chance",
        auto,
    )
    _check(await _assets(engine, run) >= 3, "asset rows enqueued for both paths")


async def render_down(engine: AsyncEngine, run: int) -> None:
    stats = await _wait_for_completion(engine, run)
    pages = await _by_host(engine, run)
    print(f"run {run} completed: {stats}")
    static, auto = pages.get("vantage.fixtures"), pages.get("orbis.fixtures")
    _check(
        static is not None and static.title == "Resin Fibre Disc 115mm P60",
        "static crawling unaffected by a stopped render",
        static,
    )
    _check(
        auto is not None and auto.strategy == "static_fallback",
        "AUTO recorded static_fallback",
        auto,
    )


async def reset(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.execute(sa.text("TRUNCATE crawl.domains, crawl.runs RESTART IDENTITY CASCADE"))


async def main(argv: list[str]) -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        if argv[0] == "reset":
            await reset(engine)
        elif argv[0] == "render-up":
            await render_up(engine, int(argv[1]))
        elif argv[0] == "render-down":
            await render_down(engine, int(argv[1]))
        else:
            raise SystemExit(__doc__)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
