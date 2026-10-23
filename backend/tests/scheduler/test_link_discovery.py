"""The crawl follows the template's discovery rules (spec 004 §1, §5;
BUILD_PLAN 2.3).

**The phase-2 exit's shape, at 2.3's size.** One seed, Halden's
`EXIT_SEED`, a listing template carrying `EXIT_DISCOVERY` and a product
template, crawled by the real worker process against the fixture site over
loopback, politely: one connection, the per-domain gate, a small delay.
What must come out is exactly `EXIT_PRODUCTS`, nothing off-host and no
facet URL ever in the queue, the depth chain cut between 5 and 6, a
completed run and a domain still `active` (ADR-0039).

The domain is the fixture site's `127.0.0.1:<port>`, so Halden's relative
links resolve onto the host the crawl is on. The four partner cards are
absolute URLs on other hosts; their look-alike forms are `discover`'s unit
tests' job (`tests/discovery/test_links.py`), where the host is `halden.test`.

Two narrower properties go through `PageCrawler` in-process, one claim at a
time, with the gate's delay skipped as `test_canonical_pages.py` does:
template matching on the canonical path, and no links from a page whose
observation halted its domain.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.clock import SystemClock
from spydra.adapters.http.httpx_fetcher import HttpxFetcher
from spydra.adapters.postgres.frontier import PostgresFrontier, url_hash
from spydra.adapters.postgres.templates import extraction_to_json
from spydra.domain.enums import FetchPath
from spydra.domain.fetch import FetchRequest
from spydra.domain.ids import DomainId, RunId
from spydra.domain.urls import canonical_url
from tests.extraction.pages import vantage_template
from tests.fixtures import catalogue
from tests.fixtures.catalogue import (
    DEEP_PREFIX,
    EXIT_DISCOVERY,
    EXIT_PRODUCTS,
    EXIT_SEED,
    FACETS,
)
from tests.fixtures.server import FixtureSite
from tests.scheduler.test_canonical_pages import build, make_due
from tests.scheduler.test_page_crawler import STUB_ONLY, ScriptedFetcher
from tests.scheduler.test_page_crawler import build as build_with
from tests.scheduler.test_worker_process import rows, run_state, wait_until, worker

pytestmark = pytest.mark.integration

# Matched on the canonical path + query (spec 001 §1). The listing pattern
# accepts a query because paginated listings are `?page=N`; product SKUs are
# upper case, so the two patterns never both match.
LISTING_PATTERN = r"^/shop/[a-z0-9/]*(\?.*)?$"
PRODUCT_PATTERN = r"/p/HT-[A-Z]+-\d+$"
DELAY_MS = 20


async def seed_halden(
    engine: AsyncEngine,
    base_url: str,
    *,
    listing_pattern: str = LISTING_PATTERN,
    listing_kind: str = "listing",
    listing_extraction: bool = False,
    seed: str = EXIT_SEED,
) -> tuple[DomainId, RunId, int]:
    """An active static domain at the fixture site with `max_depth = 5`, a
    listing template carrying `EXIT_DISCOVERY`, a product template, a run,
    and one pending depth-0 row for `seed`. Returns the listing template's
    id too."""
    host = urlsplit(base_url).netloc
    product_extraction = json.dumps(extraction_to_json(vantage_template().extraction))
    async with engine.begin() as conn:
        domain = DomainId(
            (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.domains
                            (host, state, crawl_delay_ms, configured_crawl_delay_ms,
                             max_concurrency, max_depth, next_eligible_at)
                        VALUES (:h, 'active', :d, :d, 1, 5, now() - interval '1 minute')
                        RETURNING id
                        """
                    ),
                    {"h": host, "d": DELAY_MS},
                )
            ).scalar_one()
        )
        listing = (
            await conn.execute(
                sa.text(
                    """
                    INSERT INTO crawl.templates
                        (domain_id, name, url_pattern, page_kind, version, is_active,
                         discovery, extraction, approved_at)
                    VALUES (:d, 'halden listing', :p, :k, 1, true,
                            CAST(:disc AS jsonb), CAST(:x AS jsonb), now())
                    RETURNING id
                    """
                ),
                {
                    "d": int(domain),
                    "p": listing_pattern,
                    "k": listing_kind,
                    "disc": json.dumps(EXIT_DISCOVERY),
                    "x": product_extraction if listing_extraction else "{}",
                },
            )
        ).scalar_one()
        await conn.execute(
            sa.text(
                """
                INSERT INTO crawl.templates
                    (domain_id, name, url_pattern, page_kind, version, is_active,
                     extraction, approved_at)
                VALUES (:d, 'halden product', :p, 'product', 1, true, CAST(:x AS jsonb), now())
                """
            ),
            {"d": int(domain), "p": PRODUCT_PATTERN, "x": product_extraction},
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
                "INSERT INTO crawl.crawl_queue (run_id, domain_id, url, url_hash, depth) "
                "VALUES (:r, :d, :u, :h, 0)"
            ),
            {"r": int(run), "d": int(domain), "u": base_url + seed, "h": url_hash(base_url + seed)},
        )
    return domain, run, int(listing)


def path_of(url: str) -> str:
    """Canonical path + query, for comparing however a URL was spelled."""
    parts = urlsplit(canonical_url(url))
    return f"{parts.path}?{parts.query}" if parts.query else parts.path


def is_facet(url: str) -> bool:
    keys = {pair.split("=", 1)[0] for pair in urlsplit(url).query.split("&") if pair}
    return bool(keys & {*FACETS, "view"})


# ---------------------------------------------------------------------------
# The exit crawl, through the worker process
# ---------------------------------------------------------------------------


async def test_a_crawl_from_the_exit_seed_yields_exactly_the_exit_products(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        base = site.base_url
        domain, run, _ = await seed_halden(engine, base)
        with worker(database_url, log, WORKER_STATIC="1") as proc:

            async def completed() -> bool:
                return await run_state(engine, run) == "completed"

            await wait_until(completed, proc, log, timeout=120, what="the exit crawl to complete")
            proc.terminate()
            proc.wait(timeout=30)
        requested = [path for _, path in site.requests]

    own_host = urlsplit(base).netloc
    queue = await rows(
        engine,
        "SELECT url, depth, state FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id",
        r=int(run),
    )
    queued = {path_of(r.url): r for r in queue}

    # Spec 004 §5: never leaves the host. Nothing off-host, ever in the queue.
    off_host = [r.url for r in queue if urlsplit(r.url).netloc != own_host]
    assert off_host == []

    # A faceted listing is capped by `deny_patterns`: no facet URL queued,
    # and none requested (the queue is what the site would see).
    assert [r.url for r in queue if is_facet(r.url)] == []
    assert [p for p in requested if is_facet(p)] == []

    # Depth: `/shop/deep/5/` is depth 5 and crawled; `/shop/deep/6/` is
    # depth 6 at `max_depth = 5` and never queued, never requested.
    deep5 = queued.get(f"{DEEP_PREFIX}5")
    assert deep5 is not None, "the depth chain stopped before 5"
    assert (deep5.depth, deep5.state) == (5, "done")
    assert f"{DEEP_PREFIX}6" not in queued
    assert not any(p.rstrip("/") == f"{DEEP_PREFIX}6" for p in requested)
    assert max(r.depth for r in queue) == 5

    # Exactly the exit's product set, as product pages, each observed.
    observed = await rows(
        engine,
        """
        SELECT DISTINCT p.url FROM crawl.pages p
        JOIN crawl.templates t ON t.id = p.template_id
        JOIN crawl.page_observations o ON o.page_id = p.id AND o.run_id = :r
        WHERE p.domain_id = :d AND t.page_kind = 'product'
        """,
        r=int(run),
        d=int(domain),
    )
    assert sorted(path_of(r.url) for r in observed) == sorted(
        f"/shop/p/{sku}" for sku in EXIT_PRODUCTS
    )

    # The run finished, the domain is healthy (ADR-0039: the listings did
    # not count), and nothing reached the inbox: no listing as an empty
    # extraction, no product as a missing template.
    assert {r.state for r in queue} == {"done"}
    assert await run_state(engine, run) == "completed"
    state = await rows(
        engine, "SELECT state::text AS s FROM crawl.domains WHERE id = :d", d=int(domain)
    )
    assert state[0].s == "active"
    inbox = await rows(
        engine, "SELECT url, reason FROM crawl.unknown_pages WHERE domain_id = :d", d=int(domain)
    )
    assert [tuple(r) for r in inbox] == []


# ---------------------------------------------------------------------------
# One claim at a time, through PageCrawler
# ---------------------------------------------------------------------------


async def crawl_next(engine: AsyncEngine, domain: DomainId) -> None:
    """Claim the next row and crawl it with the real static fetcher."""
    static = HttpxFetcher(SystemClock())
    try:
        await make_due(engine, domain)
        item = await PostgresFrontier(engine).claim()
        assert item is not None, "nothing claimable"
        await build(engine, static).crawl(item)
    finally:
        await static.aclose()


async def queued_paths(engine: AsyncEngine, run: RunId) -> dict[str, int]:
    return {
        path_of(r.url): r.depth
        for r in await rows(
            engine, "SELECT url, depth FROM crawl.crawl_queue WHERE run_id = :r", r=int(run)
        )
    }


async def test_a_page_fetched_with_a_trailing_slash_matches_a_template_written_without(
    clean_crawl: AsyncEngine,
) -> None:
    """The queue fetches `/shop/cutting/` as discovered (2.2). A template
    written for `^/shop/cutting$`, the canonical path, must match it: the
    page is the same page. Unmatched, it has no discovery rules and no
    template, and the crawl stops at the seed."""
    engine = clean_crawl
    with FixtureSite() as site:
        domain, run, listing = await seed_halden(
            engine, site.base_url, listing_pattern=r"^/shop/cutting$"
        )
        await crawl_next(engine, domain)

    page = await rows(
        engine, "SELECT url, template_id FROM crawl.pages WHERE domain_id = :d", d=int(domain)
    )
    assert [(path_of(r.url), r.template_id) for r in page] == [("/shop/cutting", listing)]
    assert await queued_paths(engine, run) == {
        "/shop/cutting": 0,
        "/shop/cutting/discs": 1,
        "/shop/cutting/blades": 1,
        f"{DEEP_PREFIX}1": 1,
        "/shop/p/HT-SB-001": 1,
    }
    inbox = await rows(
        engine, "SELECT reason FROM crawl.unknown_pages WHERE domain_id = :d", d=int(domain)
    )
    assert inbox == [], "the page was treated as having no template"


async def seed_empty_product_pages(
    engine: AsyncEngine, base: str, domain: DomainId, run: RunId, template_id: int, n: int
) -> None:
    """`n` product pages already observed empty in this run, under the
    product template, an hour ago. Written as SQL for the reason
    `observation_seed.py` gives."""
    at = datetime.now(UTC) - timedelta(hours=1)
    async with engine.begin() as conn:
        for i in range(n):
            url = f"{base}/shop/p/HT-ZZ-{i:03d}"
            page_id = (
                await conn.execute(
                    sa.text(
                        """
                        INSERT INTO crawl.pages (domain_id, url, url_hash, page_kind, template_id)
                        VALUES (:d, :u, :h, 'product', :t) RETURNING id
                        """
                    ),
                    {"d": int(domain), "u": url, "h": url_hash(url), "t": template_id},
                )
            ).scalar_one()
            await conn.execute(
                sa.text(
                    """
                    INSERT INTO crawl.page_observations
                        (page_id, run_id, template_id, observed_at, http_status,
                         empty_extraction)
                    VALUES (:p, :r, :t, :at, 200, true)
                    """
                ),
                {"p": page_id, "r": int(run), "t": template_id, "at": at},
            )


@pytest.mark.parametrize("halts", [False, True], ids=["active", "halted"])
async def test_a_page_whose_observation_halts_its_domain_enqueues_nothing(
    clean_crawl: AsyncEngine, halts: bool
) -> None:
    """A template approved against the wrong pages: a PRODUCT template,
    carrying discovery rules, matching the exit seed's category page, which
    has no product on it. With four such empty pages already in this first
    run, this one is the fifth and the domain goes back to review (ADR-0030).

    Its links must not be queued: the domain's rows will never be claimed,
    and the run would never finish. Without the four, the same page is one
    empty page below the minimum sample and its links are queued: the
    control that shows the rules do discover here."""
    engine = clean_crawl
    with FixtureSite() as site:
        base = site.base_url
        domain, run, template = await seed_halden(
            engine,
            base,
            listing_pattern=r"^/shop/cutting$",
            listing_kind="product",
            listing_extraction=True,
        )
        if halts:
            await seed_empty_product_pages(engine, base, domain, run, template, 4)
        await crawl_next(engine, domain)

    domain_rows = await rows(
        engine, "SELECT state::text AS s FROM crawl.domains WHERE id = :d", d=int(domain)
    )
    state = domain_rows[0].s
    queued = await queued_paths(engine, run)
    if halts:
        assert state == "awaiting_approval", "the setup did not halt the domain"
        assert queued == {"/shop/cutting": 0}
    else:
        assert state == "active"
        assert "/shop/cutting/discs" in queued


async def test_the_domains_deny_patterns_apply_to_the_crawl(clean_crawl: AsyncEngine) -> None:
    """Task "Decided": `deny_patterns` live on the domain too, and a link
    must pass both lists. The exit template's list says nothing about the
    archive; the domain's does."""
    engine = clean_crawl
    with FixtureSite() as site:
        domain, run, _ = await seed_halden(engine, site.base_url)
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE crawl.domains SET deny_patterns = :p WHERE id = :d"),
                {"p": ["^/shop/deep/"], "d": int(domain)},
            )
        await crawl_next(engine, domain)

    queued = await queued_paths(engine, run)
    assert "/shop/cutting/discs" in queued, "the seed discovered nothing at all"
    assert f"{DEEP_PREFIX}1" not in queued


# ---------------------------------------------------------------------------
# AUTO and listings (2.3 review, finding 4)
# ---------------------------------------------------------------------------


def halden_page(request: FetchRequest) -> tuple[int, str]:
    parts = urlsplit(request.url)
    rendered = catalogue.render(parts.path, parts.query, catalogue.HOST)
    assert rendered is not None, request.url
    return rendered[0], rendered[1].decode()


def server_html(request: FetchRequest) -> tuple[int, str]:
    """A JS-dependent product page's server HTML: an image-only stub. A
    listing is served as itself."""
    if "/p/" in urlsplit(request.url).path:
        return 200, STUB_ONLY
    return halden_page(request)


@pytest.mark.parametrize(
    ("seed", "renders"),
    [(EXIT_SEED, False), ("/shop/p/HT-CD-001", True)],
    ids=["listing", "product"],
)
async def test_auto_gives_a_product_page_a_second_chance_and_a_listing_none(
    clean_crawl: AsyncEngine, seed: str, renders: bool
) -> None:
    """A field-less listing is always "empty", so on an AUTO domain every
    listing was rendered after its static fetch: a second request to the
    supplier per page for nothing (ADR-0039). A product page whose static
    HTML is only a stub still gets its render."""
    engine = clean_crawl
    base = f"https://{catalogue.HOST}"
    domain, run, _ = await seed_halden(engine, base, seed=seed)
    async with engine.begin() as conn:
        await conn.execute(
            sa.text("UPDATE crawl.domains SET render_mode = 'auto' WHERE id = :d"),
            {"d": int(domain)},
        )
    static = ScriptedFetcher(FetchPath.STATIC, server_html)
    rendered = ScriptedFetcher(FetchPath.RENDERED, halden_page)

    await make_due(engine, domain)
    item = await PostgresFrontier(engine).claim()
    assert item is not None
    await build_with(engine, static, rendered).crawl(item)

    assert static.calls == [base + seed]
    assert rendered.calls == ([base + seed] if renders else [])
    if not renders:
        # The listing still discovered from its static HTML.
        assert "/shop/cutting/discs" in await queued_paths(engine, run)
