"""Every URL write stores the canonical URL (BUILD_PLAN 2.2, spec 004 §2).

Committed rows, so `clean_crawl`: the frontier, the loader and the pages
repository each open their own transaction.

What is held, per write path:

- `Frontier.enqueue`: two spellings of one URL are one queue row, and the
  row's `url` is the canonical spelling, not whichever arrived first.
- The YAML loader's seeds: the same, through `load()`.
- `PostgresPages.upsert`: two spellings are one page row, under the
  canonical URL.

`url` and `url_hash` are asserted together. A write that hashed the
canonical URL but stored the raw one would dedupe correctly and still put a
newsletter's `utm_source` in front of the operator for ever.
"""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.configuration import PostgresConfiguration
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.pages import PostgresPages
from spydra.domain.ids import DomainId, RunId
from spydra.domain.urls import canonical_url, url_hash
from spydra.load import load
from tests.adapters.postgres.seed import seed_domain, seed_run

pytestmark = pytest.mark.integration

HOST = "halden.test"
CANONICAL = f"http://{HOST}/shop/cutting/discs?a=1&b=2"
SPELLINGS = [
    f"http://{HOST}/shop/cutting/discs/?b=2&a=1&utm_source=newsletter#top",
    "HTTP://HALDEN.TEST:80/shop/cutting/./discs//?a=1&b=2&gclid=abc",
]


async def _queue(engine: AsyncEngine, run: RunId) -> list[sa.Row[tuple[str, bytes]]]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT url, url_hash FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id"
                    ),
                    {"r": int(run)},
                )
            ).all()
        )


async def _pages(engine: AsyncEngine, domain: DomainId) -> list[sa.Row[tuple[int, str, bytes]]]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT id, url, url_hash FROM crawl.pages WHERE domain_id = :d ORDER BY id"
                    ),
                    {"d": int(domain)},
                )
            ).all()
        )


# ---------------------------------------------------------------------------
# Frontier.enqueue
# ---------------------------------------------------------------------------


async def test_enqueue_stores_the_canonical_url(clean_crawl: AsyncEngine) -> None:
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])

    await PostgresFrontier(clean_crawl).enqueue(run, domain, [(SPELLINGS[0], 1)])

    assert [(r.url, bytes(r.url_hash)) for r in await _queue(clean_crawl, run)] == [
        (CANONICAL, url_hash(CANONICAL))
    ]


async def test_two_spellings_of_one_url_enqueue_one_row(clean_crawl: AsyncEngine) -> None:
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])
    frontier = PostgresFrontier(clean_crawl)

    inserted = await frontier.enqueue(run, domain, [(SPELLINGS[0], 1), (SPELLINGS[1], 1)])
    # A second call, as a second worker discovering the same link would make.
    again = await frontier.enqueue(run, domain, [(f"{CANONICAL}#reviews", 2)])

    assert (inserted, again) == (1, 0)
    assert [r.url for r in await _queue(clean_crawl, run)] == [CANONICAL]


async def test_enqueue_keeps_two_different_pages_apart(clean_crawl: AsyncEngine) -> None:
    """The other half: `?page=2` is meaningful and must not collapse."""
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])
    base = f"http://{HOST}/shop/cutting/discs"

    inserted = await PostgresFrontier(clean_crawl).enqueue(
        run, domain, [(f"{base}/", 1), (f"{base}?page=2&utm_source=x", 1)]
    )

    assert inserted == 2
    assert sorted(r.url for r in await _queue(clean_crawl, run)) == [base, f"{base}?page=2"]


async def test_enqueue_never_stores_credentials(clean_crawl: AsyncEngine) -> None:
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])

    await PostgresFrontier(clean_crawl).enqueue(
        run, domain, [(f"http://user:secret@{HOST}/shop/p/HT-SB-001", 1)]
    )

    assert [r.url for r in await _queue(clean_crawl, run)] == [f"http://{HOST}/shop/p/HT-SB-001"]


# ---------------------------------------------------------------------------
# The YAML loader's seeds
# ---------------------------------------------------------------------------

_YAML = f"""
domains:
  - host: {HOST}
    scheme: http
    render_mode: static
    crawl_delay_ms: 2500
    templates:
      - name: product
        url_pattern: "/shop/p/.+"
        extraction:
          title: {{ selector: "h1" }}
    seeds:
      - "/shop/cutting/discs/?b=2&a=1&utm_source=newsletter#top"
      - "HTTP://HALDEN.TEST/shop/cutting/./discs//?a=1&b=2&gclid=abc"
      - "/shop//finishing/../grinding/"
"""


async def test_the_loader_stores_canonical_seed_urls_and_dedupes_spellings(
    clean_crawl: AsyncEngine,
) -> None:
    run = await load(PostgresConfiguration(clean_crawl), _YAML)

    rows = await _queue(clean_crawl, run)
    grinding = f"http://{HOST}/shop/grinding"
    assert sorted(r.url for r in rows) == sorted([CANONICAL, grinding])
    assert all(bytes(r.url_hash) == url_hash(r.url) for r in rows)
    assert all(canonical_url(r.url) == r.url for r in rows)


# ---------------------------------------------------------------------------
# PostgresPages.upsert
# ---------------------------------------------------------------------------


async def test_two_spellings_of_one_page_upsert_one_row_under_the_canonical_url(
    clean_crawl: AsyncEngine,
) -> None:
    domain = await seed_domain(clean_crawl, HOST)
    pages = PostgresPages(clean_crawl)

    first = await pages.upsert(domain, SPELLINGS[0], depth=1, template_id=None, page_kind=None)
    second = await pages.upsert(domain, SPELLINGS[1], depth=1, template_id=None, page_kind=None)

    assert first == second
    assert [(r.url, bytes(r.url_hash)) for r in await _pages(clean_crawl, domain)] == [
        (CANONICAL, url_hash(CANONICAL))
    ]
