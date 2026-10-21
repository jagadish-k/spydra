"""`asset_queue` writes and the claim brake, against real Postgres (1.12).

ADR-0003's words are "it never blocks on an image", and the only honest test
of that is a **timing** one against a server that would make a fetch visible.
`1.4` serves every `/img/slow/` image behind a 150 ms delay — built for spec
012's `block_resources` criterion, and exactly what is needed here. A test
that counted rows would pass against an enqueue that downloaded all six
images first.
"""

import time
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.assets import PostgresAssets
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.domain.ids import ObservationId, RunId
from spydra.scheduler.asset_pressure import AssetPressure
from tests.adapters.postgres.observation_seed import (
    seed_observation,
    seed_page,
    seed_template,
)
from tests.adapters.postgres.seed import seed_domain, seed_queue_row, seed_run
from tests.fixtures.server import SLOW_IMAGE_DELAY_S, SLOW_IMAGE_PREFIX, FixtureSite

pytestmark = pytest.mark.integration


@pytest.fixture
def site() -> Iterator[FixtureSite]:
    with FixtureSite() as fixture_site:
        yield fixture_site


async def an_observation(
    engine: AsyncEngine, *, state: str = "active", host: str = "vantage-abrasives.test"
) -> tuple[RunId, ObservationId]:
    """A run and one observation for `asset_queue`'s NOT NULL FK to hang off.

    `state` is a parameter because of ADR-0026's claim: it locks the single
    most-eligible domain and claims a row OF THAT DOMAIN, so an extra
    `active` domain with an empty queue makes `claim()` return `None` while
    pending rows sit under another host. The claiming test below therefore
    parks this domain rather than leaving it eligible — measured as three
    `None` claims, which read exactly like a broken brake.
    """
    domain_id = await seed_domain(engine, host=host, state=state)
    template_id = await seed_template(engine, domain_id)
    run_id = await seed_run(engine, [int(domain_id)])
    page_id = await seed_page(
        engine, domain_id, "https://v.test/catalog/a", template_id=template_id
    )
    observation_id = await seed_observation(
        engine, page_id, run_id, empty=False, observed_at=datetime.now(UTC)
    )
    return run_id, ObservationId(observation_id)


async def queue_rows(engine: AsyncEngine) -> list[sa.Row[tuple[object, ...]]]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT source_url, source_host, position, state, attempts "
                        "FROM crawl.asset_queue ORDER BY position"
                    )
                )
            ).all()
        )


# ---------------------------------------------------------------------------
# Spec 008 §1 step 1: insert and move on
# ---------------------------------------------------------------------------


async def test_six_images_leave_six_rows_in_page_order(clean_crawl: AsyncEngine) -> None:
    """BUILD_PLAN 1.12's first criterion, with `position` asserted: a gallery
    is ordered and `observation_assets.position` exists to carry that."""
    engine = clean_crawl
    run_id, observation_id = await an_observation(engine)
    urls = tuple(f"https://cdn.v.test/img/{i}.jpg" for i in range(6))

    inserted = await PostgresAssets(engine).enqueue(run_id, observation_id, urls)

    rows = await queue_rows(engine)
    assert inserted == 6
    assert [r.source_url for r in rows] == list(urls)
    assert [r.position for r in rows] == [0, 1, 2, 3, 4, 5]
    assert {r.state for r in rows} == {"pending"}
    assert {r.source_host for r in rows} == {"cdn.v.test"}


async def test_the_enqueue_does_not_fetch_the_images(
    clean_crawl: AsyncEngine, site: FixtureSite
) -> None:
    """ADR-0003: "it never blocks on an image".

    Six images at 150 ms each is 900 ms of downloading. The enqueue has to
    finish in a fraction of one of them, and the **control** below proves the
    route really is slow — without it this test would pass against a fetching
    enqueue the day someone made the fixture fast.
    """
    engine = clean_crawl
    run_id, observation_id = await an_observation(engine)
    urls = tuple(f"{site.base_url}{SLOW_IMAGE_PREFIX}{i:02d}.png" for i in range(6))

    started = time.monotonic()
    inserted = await PostgresAssets(engine).enqueue(run_id, observation_id, urls)
    enqueueing = time.monotonic() - started

    # The control: one real fetch of one of those URLs.
    control_started = time.monotonic()
    with urllib.request.urlopen(urls[0], timeout=5) as response:
        assert response.read()
    one_download = time.monotonic() - control_started

    assert inserted == 6
    assert one_download >= SLOW_IMAGE_DELAY_S, (
        f"the fixture's slow image route returned in {one_download:.3f}s, so this "
        "test can no longer tell a fetching enqueue from a non-fetching one"
    )
    assert enqueueing < one_download, (
        f"enqueueing six images took {enqueueing:.3f}s and one download takes "
        f"{one_download:.3f}s — the enqueue is fetching"
    )
    # Nothing in the queue was requested from the server at all.
    assert [path for _host, path in site.requests] == [f"{SLOW_IMAGE_PREFIX}00.png"], (
        "the only request should be the control's"
    )


async def test_re_enqueueing_the_same_page_adds_nothing(clean_crawl: AsyncEngine) -> None:
    """`UNIQUE (observation_id, source_url)` (spec 001 §1). A re-crawl is a
    no-op rather than an IntegrityError mid-crawl, and the returned count is
    the INSERTED rows so `1.13`'s log does not claim work it did not do."""
    engine = clean_crawl
    run_id, observation_id = await an_observation(engine)
    urls = ("https://cdn.v.test/a.jpg", "https://cdn.v.test/b.jpg")
    assets = PostgresAssets(engine)

    assert await assets.enqueue(run_id, observation_id, urls) == 2
    assert await assets.enqueue(run_id, observation_id, urls) == 0
    assert len(await queue_rows(engine)) == 2


async def test_a_duplicated_url_on_one_page_is_one_row(clean_crawl: AsyncEngine) -> None:
    """The dedupe is in `asset_urls`, so this is the belt to that braces: a
    caller that passed the same URL twice must not hit the constraint."""
    engine = clean_crawl
    run_id, observation_id = await an_observation(engine)

    inserted = await PostgresAssets(engine).enqueue(
        run_id, observation_id, ("https://cdn.v.test/a.jpg", "https://cdn.v.test/a.jpg")
    )

    assert inserted == 1


async def test_a_page_with_no_images_costs_no_statement(clean_crawl: AsyncEngine) -> None:
    """Most listing pages. Asserted for the count rather than the round trip,
    which only a query log could see — the behaviour that matters is that an
    empty gallery is not an error."""
    engine = clean_crawl
    run_id, observation_id = await an_observation(engine)

    assert await PostgresAssets(engine).enqueue(run_id, observation_id, ()) == 0
    assert await queue_rows(engine) == []


async def test_the_host_is_normalised_for_the_asset_gate(clean_crawl: AsyncEngine) -> None:
    """`5.2`'s `AssetGate` keys its per-host semaphore on `source_host`
    (spec 002 §6), so `CDN.test` and `cdn.test:443` have to be one host —
    otherwise one CDN gets several independent concurrency budgets, which is
    how a polite crawler hammers one origin."""
    engine = clean_crawl
    run_id, observation_id = await an_observation(engine)

    await PostgresAssets(engine).enqueue(
        run_id,
        observation_id,
        ("https://CDN.V.test/a.jpg", "https://cdn.v.test:443/b.jpg"),
    )

    assert {r.source_host for r in await queue_rows(engine)} == {"cdn.v.test"}


async def test_pending_counts_only_what_is_waiting(clean_crawl: AsyncEngine) -> None:
    """The backpressure input (spec 002 §7). A queue that counted drained
    rows would engage the brake permanently after the first busy run, since
    nothing deletes from this table."""
    engine = clean_crawl
    run_id, observation_id = await an_observation(engine)
    assets = PostgresAssets(engine)
    await assets.enqueue(run_id, observation_id, ("https://cdn.v.test/a.jpg",))
    await assets.enqueue(run_id, observation_id, ("https://cdn.v.test/b.jpg",))

    assert await assets.pending() == 2

    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE crawl.asset_queue SET state = 'done' WHERE position = 0")
        )

    assert await assets.pending() == 1


# ---------------------------------------------------------------------------
# Spec 002 §7: a deep queue slows page claiming
# ---------------------------------------------------------------------------


async def seed_pending_assets(engine: AsyncEngine, count: int) -> None:
    """`count` pending rows, in one statement.

    `generate_series` rather than a Python loop: 10,001 round trips is a
    minute of test time, and the thing under test is the brake, not the
    insert.
    """
    # Parked: an eligible domain with no pending URLs would starve the claim
    # (see `an_observation`).
    run_id, observation_id = await an_observation(engine, state="paused", host="assets.test")
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                """
                INSERT INTO crawl.asset_queue
                    (run_id, observation_id, source_url, source_host, position)
                SELECT :run, :obs, 'https://cdn.v.test/bulk/' || i || '.jpg',
                       'cdn.v.test', i
                FROM generate_series(1, :count) AS s(i)
                """
            ),
            {"run": int(run_id), "obs": int(observation_id), "count": count},
        )


@pytest.mark.parametrize(
    ("pending_rows", "expect_slowed"),
    [(10_001, True), (7_999, False)],
)
async def test_a_deep_asset_queue_measurably_slows_page_claiming(
    clean_crawl: AsyncEngine, pending_rows: int, expect_slowed: bool
) -> None:
    """BUILD_PLAN 1.12's second criterion, end to end and on observed
    timestamps: real `asset_queue` rows, the real count query, the real
    frontier claim.

    The parametrised pair is what makes it a measurement — a single slowed
    case would pass against a brake that is always on, which would be a
    worker that crawls at two pages a second for ever.
    """
    engine = clean_crawl
    await seed_pending_assets(engine, pending_rows)
    domain_id = await seed_domain(engine, host="claiming.test", max_concurrency=3)
    run_id = await seed_run(engine, [int(domain_id)])
    for i in range(3):
        await seed_queue_row(engine, run_id, domain_id, f"https://claiming.test/p{i}")

    assets = PostgresAssets(engine)
    frontier = PostgresFrontier(engine)
    pressure = AssetPressure(sleep_ms=100)

    started = time.monotonic()
    claimed = []
    for _ in range(3):
        await pressure.before_claim(await assets.pending())
        claimed.append(await frontier.claim())
    elapsed = time.monotonic() - started

    # Anti-vacuity: claiming really happened. "Slowed" must not be able to
    # mean "claimed nothing".
    assert all(c is not None for c in claimed), claimed
    assert pressure.engaged is expect_slowed
    if expect_slowed:
        assert elapsed >= 0.3, f"three braked claims took {elapsed:.3f}s"
    else:
        assert elapsed < 0.3, f"three unbraked claims took {elapsed:.3f}s"
