"""Every URL write keys on the canonical URL (BUILD_PLAN 2.2, spec 004 §2).

Committed rows, so `clean_crawl`: the frontier, the loader and the pages
repository each open their own transaction.

What is held, per write path (contract as amended by the 2.2 review):

- `Frontier.enqueue` and the YAML loader's seeds: two spellings of one URL
  are one queue row, because `url_hash` is the canonical URL's hash. The
  row's `url` is the **fetchable** spelling of whichever arrived first: as
  written, minus the fragment and any `user:pass@`. Spec 004 §2
  canonicalises before hashing, not before fetching. A site that 301s `/x`
  to `/x/` would otherwise cost a redirect per page.
- `PostgresPages.upsert`: two spellings are one page row, under the
  canonical URL.

Credentials and fragments are asserted absent from every stored URL: a
`user:pass@` in the queue is logged with every line about the page.
"""

import hashlib

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.configuration import PostgresConfiguration
from spydra.adapters.postgres.frontier import PostgresFrontier
from spydra.adapters.postgres.pages import PostgresPages
from spydra.domain.ids import DomainId, RunId
from spydra.load import load
from tests.adapters.postgres.seed import seed_domain, seed_run

pytestmark = pytest.mark.integration

HOST = "halden.test"
CANONICAL = f"http://{HOST}/shop/cutting/discs?a=1&b=2"
SPELLINGS = [
    f"http://{HOST}/shop/cutting/discs/?b=2&a=1&utm_source=newsletter#top",
    f"http://{HOST}/shop/cutting/./discs//?a=1&b=2&gclid=abc",
]
# What the queue fetches for each: as written, fragment gone.
FETCHABLE = [
    f"http://{HOST}/shop/cutting/discs/?b=2&a=1&utm_source=newsletter",
    f"http://{HOST}/shop/cutting/./discs//?a=1&b=2&gclid=abc",
]


def sha(url: str) -> bytes:
    return hashlib.sha256(url.encode("utf-8")).digest()


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


@pytest.mark.parametrize("which", [0, 1])
async def test_enqueue_stores_the_fetchable_spelling_under_the_canonical_hash(
    clean_crawl: AsyncEngine, which: int
) -> None:
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])

    await PostgresFrontier(clean_crawl).enqueue(run, domain, [(SPELLINGS[which], 1)])

    assert [(r.url, bytes(r.url_hash)) for r in await _queue(clean_crawl, run)] == [
        (FETCHABLE[which], sha(CANONICAL))
    ]


@pytest.mark.parametrize("first", [0, 1])
async def test_two_spellings_of_one_url_enqueue_one_row_holding_the_first(
    clean_crawl: AsyncEngine, first: int
) -> None:
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])
    frontier = PostgresFrontier(clean_crawl)
    other = 1 - first

    inserted = await frontier.enqueue(run, domain, [(SPELLINGS[first], 1), (SPELLINGS[other], 1)])
    # A second call, as a second worker discovering the same link would make.
    again = await frontier.enqueue(run, domain, [(f"{CANONICAL}#reviews", 2)])

    assert (inserted, again) == (1, 0)
    assert [r.url for r in await _queue(clean_crawl, run)] == [FETCHABLE[first]]


async def test_enqueue_keeps_two_different_pages_apart(clean_crawl: AsyncEngine) -> None:
    """The other half: `?page=2` is meaningful and must not collapse."""
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])
    base = f"http://{HOST}/shop/cutting/discs"

    inserted = await PostgresFrontier(clean_crawl).enqueue(
        run, domain, [(f"{base}/", 1), (f"{base}?page=2", 1)]
    )

    assert inserted == 2
    assert {bytes(r.url_hash) for r in await _queue(clean_crawl, run)} == {
        sha(base),
        sha(f"{base}?page=2"),
    }


@pytest.mark.parametrize(
    ("url", "stored"),
    [
        (f"http://user:secret@{HOST}/shop/p/HT-SB-001", f"http://{HOST}/shop/p/HT-SB-001"),
        (f"http://user@{HOST}/shop/p/HT-SB-001#specs", f"http://{HOST}/shop/p/HT-SB-001"),
        (
            f"http://u:p@{HOST}:8080/shop/p/HT-SB-001/?ref=x#top",
            f"http://{HOST}:8080/shop/p/HT-SB-001/?ref=x",
        ),
    ],
)
async def test_enqueue_never_stores_credentials_or_a_fragment(
    clean_crawl: AsyncEngine, url: str, stored: str
) -> None:
    domain = await seed_domain(clean_crawl, HOST)
    run = await seed_run(clean_crawl, [int(domain)])

    await PostgresFrontier(clean_crawl).enqueue(run, domain, [(url, 1)])

    (row,) = await _queue(clean_crawl, run)
    assert row.url == stored
    assert "secret" not in row.url and "@" not in row.url and "#" not in row.url


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
      - "/shop//finishing/../grinding/#x"
"""


async def test_the_loader_dedupes_seed_spellings_and_stores_the_fetchable_one(
    clean_crawl: AsyncEngine,
) -> None:
    run = await load(PostgresConfiguration(clean_crawl), _YAML)

    rows = await _queue(clean_crawl, run)
    assert sorted((r.url, bytes(r.url_hash)) for r in rows) == sorted(
        [
            (FETCHABLE[0], sha(CANONICAL)),
            (
                f"http://{HOST}/shop//finishing/../grinding/",
                sha(f"http://{HOST}/shop/grinding"),
            ),
        ]
    )
    assert all("#" not in r.url for r in rows)


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
        (CANONICAL, sha(CANONICAL))
    ]
