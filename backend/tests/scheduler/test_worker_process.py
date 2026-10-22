"""The worker as a process: `python -m spydra.worker` (BUILD_PLAN 1.13).

**The real thing, end to end.** A subprocess running the module compose
runs, with real fetchers against the loopback fixture site and the real test
database. These tests seed rows, start the process, watch the database, and
signal it, and every assertion is on what an operator would see: the rows,
the exit code, and stdout.

- **End to end:** seeded fixture URLs are crawled to completion.
- **SIGTERM** (spec 002 / the 1.13 contract): exit 0 inside the grace, no
  row left `in_flight`, every `in_flight` counter back to 0. Both halves:
  pages that finish inside the grace, and a page that does not, which must
  be cancelled and released rather than waited for.
- **The log** (spec 009 §1, §5): a 1,000-page run at `info` writes fewer
  than 100 lines; no line carries a body, a tag or a credential; at `debug`
  every crawl-path line carries its context.

The render sidecar is pointed at a closed loopback port: every domain here
is static, and a test that needed the sidecar would be testing the sidecar.
"""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.frontier import url_hash
from spydra.adapters.postgres.templates import extraction_to_json
from spydra.domain.ids import DomainId, RunId
from tests.extraction.pages import vantage_template
from tests.fixtures.server import GENERATED_COOKIE_VALUE, FixtureSite

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[2]
UA = "SpydraTest/1.0 (+https://spydra.test)"
CLOSED_PORT = "http://127.0.0.1:9"

PRODUCT = "/catalog/abrasives/discs/rfd-115-060"
FIXTURE_PATHS = [
    PRODUCT,
    "/catalog/abrasives/discs/",
    "/fixings/hex-set-screw-m8x40",
    "/katalog/discontinued-item",
    "/catalog/no-such-page",
]


# ---------------------------------------------------------------------------
# Seeding and watching
# ---------------------------------------------------------------------------


async def seed_site(
    engine: AsyncEngine,
    base_url: str,
    paths: list[str],
    *,
    delay_ms: int = 0,
    max_concurrency: int = 1,
    url_pattern: str = "/catalog/.+",
) -> tuple[DomainId, RunId]:
    """An active static domain at the fixture site's `host:port`, its
    approved vantage template, a run, and one pending row per path."""
    host = urlsplit(base_url).netloc
    async with engine.begin() as conn:
        domain = DomainId(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.domains
                            (host, state, crawl_delay_ms, configured_crawl_delay_ms,
                             max_concurrency, next_eligible_at)
                        VALUES (:h, 'active', :d, :d, :mc, now() - interval '1 minute')
                        RETURNING id
                        """
                    ),
                    {"h": host, "d": delay_ms, "mc": max_concurrency},
                )
            ).scalar_one()
        )
        await conn.execute(
            sa.text(
                """
                INSERT INTO crawl.templates
                    (domain_id, name, url_pattern, page_kind, version, is_active,
                     extraction, approved_at)
                VALUES (:d, 'vantage product', :p, 'product', 1, true, CAST(:x AS jsonb), now())
                """
            ),
            {
                "d": int(domain),
                "p": url_pattern,
                "x": json.dumps(extraction_to_json(vantage_template().extraction)),
            },
        )
        run = RunId(
            (
                await conn.execute(
                    sa.text("INSERT INTO crawl.runs (domain_ids) VALUES (:ids) RETURNING id"),
                    {"ids": [int(domain)]},
                )
            ).scalar_one()
        )
        await conn.execute(
            sa.text(
                "INSERT INTO crawl.crawl_queue (run_id, domain_id, url, url_hash) "
                "VALUES (:r, :d, :u, :h)"
            ),
            [
                {"r": int(run), "d": int(domain), "u": base_url + p, "h": url_hash(base_url + p)}
                for p in paths
            ],
        )
    return domain, run


async def scalar(engine: AsyncEngine, sql: str, **params: Any) -> Any:
    async with engine.connect() as conn:
        return (await conn.execute(sa.text(sql), params)).scalar_one()


async def rows(engine: AsyncEngine, sql: str, **params: Any) -> list[sa.Row[Any]]:
    async with engine.connect() as conn:
        return list((await conn.execute(sa.text(sql), params)).all())


async def run_state(engine: AsyncEngine, run: RunId) -> str:
    return str(await scalar(engine, "SELECT state::text FROM crawl.runs WHERE id = :r", r=int(run)))


async def assert_nothing_left_in_flight(engine: AsyncEngine) -> None:
    in_flight_rows = await scalar(
        engine, "SELECT count(*) FROM crawl.crawl_queue WHERE state = 'in_flight'"
    )
    counters = [tuple(r) for r in await rows(engine, "SELECT host, in_flight FROM crawl.domains")]
    assert in_flight_rows == 0, "a row was left in_flight"
    assert all(n == 0 for _, n in counters), f"in_flight counters not reconciled: {counters}"


# ---------------------------------------------------------------------------
# The process
# ---------------------------------------------------------------------------


@contextmanager
def worker(database_url: str, log: Path, **env: str) -> Iterator[subprocess.Popen[bytes]]:
    """`python -m spydra.worker`, stdout and stderr to `log`.

    A file rather than a pipe: at `debug` the worker writes faster than a
    test that is busy polling the database drains a pipe, and a full pipe
    blocks the worker mid-write, which reads exactly like a hung shutdown.
    """
    environment = {
        **os.environ,
        "DATABASE_URL": database_url,
        "USER_AGENT": UA,
        "RENDER_BASE_URL": CLOSED_PORT,
        "WORKER_STATIC": "2",
        "WORKER_RENDERED": "1",
        "SHUTDOWN_GRACE_S": "10",
        "LOG_LEVEL": "info",
        **env,
    }
    with log.open("wb") as out:
        proc = subprocess.Popen(
            [sys.executable, "-m", "spydra.worker"],
            cwd=BACKEND_ROOT,
            env=environment,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
        try:
            yield proc
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)


def sigterm(proc: subprocess.Popen[bytes], timeout: float) -> tuple[int | None, float]:
    """Send SIGTERM; the exit code and how long the process took to go, or
    `None` if it outlived `timeout`."""
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, time.monotonic() - started
    return code, time.monotonic() - started


async def wait_until(
    condition: Callable[[], Awaitable[bool]],
    proc: subprocess.Popen[bytes],
    log: Path,
    *,
    timeout: float,
    what: str,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"the worker exited early ({proc.returncode}):\n{log.read_text()[-4000:]}")
        if await condition():
            return
        await asyncio.sleep(0.1)
    pytest.fail(f"timed out waiting for {what}:\n{log.read_text()[-4000:]}")


def log_lines(log: Path) -> list[str]:
    return [line for line in log.read_text().splitlines() if line.strip()]


# A tag, a closing tag, a doctype or a comment: any of them in a log line
# means markup got there.
_MARKUP = re.compile(r"<\s*[a-zA-Z!/]")
_CREDENTIALS = ("set-cookie", "authorization", GENERATED_COOKIE_VALUE.lower())


def assert_no_body_or_credential(lines: list[str]) -> None:
    for line in lines:
        assert not _MARKUP.search(line), f"markup in the log: {line[:300]}"
        lowered = line.lower()
        for secret in _CREDENTIALS:
            assert secret not in lowered, f"{secret!r} in the log: {line[:300]}"


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------


async def test_the_worker_crawls_seeded_fixture_urls_to_completion(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        domain, run = await seed_site(clean_crawl, site.base_url, FIXTURE_PATHS)
        with worker(database_url, log) as proc:

            async def completed() -> bool:
                return await run_state(clean_crawl, run) == "completed"

            await wait_until(completed, proc, log, timeout=60, what="the run to complete")
            code, _ = sigterm(proc, timeout=30)

        requested = {path for _, path in site.requests}

    assert code == 0, log.read_text()[-4000:]
    assert set(FIXTURE_PATHS) <= requested, "every seeded URL was fetched from the site"

    states = await rows(clean_crawl, "SELECT url, state FROM crawl.crawl_queue ORDER BY id")
    assert {r.state for r in states} == {"done"}, states

    product = await rows(
        clean_crawl,
        """
        SELECT o.title, o.price_amount, o.http_status FROM crawl.page_observations o
        JOIN crawl.pages p ON p.id = o.page_id WHERE p.url = :u
        """,
        u=site.base_url + PRODUCT,
    )
    assert [tuple(r) for r in product] == [("Resin Fibre Disc 115mm P60", Decimal("14.75"), 200)]
    dead = await scalar(
        clean_crawl,
        """
        SELECT o.http_status FROM crawl.page_observations o
        JOIN crawl.pages p ON p.id = o.page_id WHERE p.url = :u
        """,
        u=site.base_url + "/catalog/no-such-page",
    )
    assert dead == 404

    assets = {
        r[0]
        for r in await rows(
            clean_crawl, "SELECT source_url FROM crawl.asset_queue WHERE run_id = :r", r=int(run)
        )
    }
    assert site.base_url + "/img/rfd-115-060-a.jpg" in assets
    assert site.base_url + "/img/rfd-115-060-b.jpg" in assets

    finished = (
        await rows(
            clean_crawl,
            "SELECT state::text, finished_at, stats FROM crawl.runs WHERE id = :r",
            r=int(run),
        )
    )[0]
    assert finished.state == "completed"
    assert finished.finished_at is not None
    assert isinstance(finished.stats, dict) and finished.stats, "stats populated on completion"
    # Spec 009 §2's shape: the keys an operator reads after a run.
    stats = finished.stats
    assert stats["pages_crawled"] == len(states)
    assert stats["pages_failed"] == 0
    assert stats["by_strategy"].get("selector", 0) >= 1
    assert stats["assets_enqueued"] >= 2
    assert isinstance(stats["duration_s"], int)
    await assert_nothing_left_in_flight(clean_crawl)
    assert (
        await scalar(
            clean_crawl, "SELECT state::text FROM crawl.domains WHERE id = :d", d=int(domain)
        )
        == "active"
    )


# ---------------------------------------------------------------------------
# SIGTERM
# ---------------------------------------------------------------------------


async def test_sigterm_lets_in_flight_pages_finish_inside_the_grace_and_exits_0(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """Pages take 1.5 s, the grace is 10 s. Claiming stops at once; what the
    site had already been asked for completes; the rest stays pending for
    the next worker; and the process does not sit out the whole grace."""
    grace_s = 10.0
    log = tmp_path / "worker.log"
    paths = [f"/slow/1500/{n}" for n in range(8)]
    with FixtureSite() as site:
        _, run = await seed_site(clean_crawl, site.base_url, paths, max_concurrency=2)
        with worker(database_url, log, SHUTDOWN_GRACE_S=str(grace_s)) as proc:

            async def fetching() -> bool:
                return any(p.startswith("/slow/") for _, p in site.requests)

            await wait_until(fetching, proc, log, timeout=30, what="a page to be in flight")
            code, elapsed = sigterm(proc, timeout=grace_s + 10)
        requested = {site.base_url + p for _, p in site.requests if p.startswith("/slow/")}

    assert code == 0, log.read_text()[-4000:]
    assert elapsed < grace_s, f"took {elapsed:.1f}s: it waited out the grace for nothing"
    await assert_nothing_left_in_flight(clean_crawl)
    states = {
        r.url: r.state
        for r in await rows(
            clean_crawl, "SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r", r=int(run)
        )
    }
    assert requested, "nothing was in flight when the signal was sent"
    for url, state in states.items():
        expected = "done" if url in requested else "pending"
        assert state == expected, f"{url}: {state}, expected {expected} ({states})"
    assert "pending" in states.values(), "claiming did not stop on SIGTERM"


async def test_sigterm_cancels_a_page_that_overruns_the_grace_and_releases_its_row(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """A page that will take 15 s, a 1 s grace. The process must not wait
    for the page: it cancels it, gives the row back with no attempt charged
    and the domain's gate released, and exits 0."""
    grace_s = 1.0
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        domain, run = await seed_site(clean_crawl, site.base_url, ["/slow/15000/a"])
        with worker(database_url, log, SHUTDOWN_GRACE_S=str(grace_s), WORKER_STATIC="1") as proc:

            async def fetching() -> bool:
                return any(p.startswith("/slow/") for _, p in site.requests)

            await wait_until(fetching, proc, log, timeout=30, what="the slow page to be in flight")
            code, elapsed = sigterm(proc, timeout=grace_s + 10)

    assert code == 0, log.read_text()[-4000:]
    assert elapsed < grace_s + 5, f"took {elapsed:.1f}s: the overrunning page was waited for"
    await assert_nothing_left_in_flight(clean_crawl)
    row = (
        await rows(
            clean_crawl,
            "SELECT state, attempts, locked_until FROM crawl.crawl_queue WHERE run_id = :r",
            r=int(run),
        )
    )[0]
    assert (row.state, row.attempts, row.locked_until) == ("pending", 0, None)
    assert (
        await scalar(
            clean_crawl,
            "SELECT consecutive_failures FROM crawl.domains WHERE id = :d",
            d=int(domain),
        )
        == 0
    )
    assert await run_state(clean_crawl, run) == "running"


# ---------------------------------------------------------------------------
# The log (spec 009 §1, §5)
# ---------------------------------------------------------------------------

LIFECYCLE = frozenset({"worker_started", "worker_stopped", "run_finished"})


async def test_a_1000_page_run_at_info_writes_under_100_lines_with_no_body_or_credential(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    log = tmp_path / "worker.log"
    paths = [f"/generated/{n}" for n in range(1000)]
    with FixtureSite() as site:
        _, run = await seed_site(
            clean_crawl, site.base_url, paths, max_concurrency=4, url_pattern=r"/generated/\d+"
        )
        with worker(database_url, log, WORKER_STATIC="4") as proc:

            async def completed() -> bool:
                return await run_state(clean_crawl, run) == "completed"

            await wait_until(completed, proc, log, timeout=240, what="the 1,000-page run")
            code, _ = sigterm(proc, timeout=30)

    assert code == 0, log.read_text()[-4000:]
    crawled = await scalar(
        clean_crawl,
        "SELECT count(*) FROM crawl.page_observations WHERE run_id = :r AND title IS NOT NULL",
        r=int(run),
    )
    assert crawled == 1000, "the budget only means something over a real 1,000-page crawl"

    lines = log_lines(log)
    assert len(lines) < 100, f"{len(lines)} lines at info for 1,000 pages"
    for line in lines:
        json.loads(line)  # spec 009 §1: JSON to stdout, every line
    assert_no_body_or_credential(lines)


async def test_at_debug_every_crawl_path_line_carries_its_context_and_no_body_or_credential(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    log = tmp_path / "worker.log"
    paths = FIXTURE_PATHS + [f"/generated/{n}" for n in range(20)]
    with FixtureSite() as site:
        _, run = await seed_site(
            clean_crawl, site.base_url, paths, url_pattern=r"/(catalog/.+|generated/\d+)"
        )
        with worker(database_url, log, LOG_LEVEL="debug") as proc:

            async def completed() -> bool:
                return await run_state(clean_crawl, run) == "completed"

            await wait_until(completed, proc, log, timeout=60, what="the run to complete")
            code, _ = sigterm(proc, timeout=30)

    assert code == 0, log.read_text()[-4000:]
    lines = log_lines(log)
    assert_no_body_or_credential(lines)

    records = [json.loads(line) for line in lines]
    crawled = [r for r in records if r.get("event") == "page_crawled"]
    assert len(crawled) == len(paths), "debug logs each page"

    missing = [
        r
        for r in records
        if r.get("event") not in LIFECYCLE
        and any(r.get(key) is None for key in ("run_id", "domain", "url", "attempt"))
    ]
    assert missing == [], f"crawl-path lines without their context: {missing[:3]}"
    # `strategy` is on every page line. It is null only where no strategy
    # produced anything (an empty extraction), which is the true answer.
    assert all("strategy" in r for r in crawled)
    unnamed = [r for r in crawled if not r["empty"] and not r["strategy"]]
    assert unnamed == [], f"page lines that do not name the strategy that ran: {unnamed[:3]}"
    assert {r["run_id"] for r in crawled} == {int(run)}
