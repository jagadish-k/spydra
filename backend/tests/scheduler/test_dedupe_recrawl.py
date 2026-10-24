"""Within-run dedupe and the re-crawl's re-fill, through the real worker
(BUILD_PLAN 2.4, spec 001 §1; spec 004 §1 rule 6).

**A prove-and-pin slice.** The queue's `UNIQUE (run_id, url_hash)` has existed
since 1.1 and the guarded `ON CONFLICT` enqueue since 2.3, but the 2.3 exit
crawl never exercises the constraint: every one of its 44 URLs is discovered
exactly once. These two crawls are the ones that do:

- **The mega crawl** — the listing rule widened onto `nav.mega a`, so every
  category is re-discovered from every listing page and product page's menu.
  Without the within-run dedupe the second discovery of `/shop/cutting/discs`
  raises on the constraint and the crawl dies; with it the queue is exactly
  the 84-row mega shape (derived from the catalogue constants below), every
  category once, all 64 products observed.
- **The re-crawl** — both runs created by `PostgresConfiguration.apply`, the
  one production run-creation path (`spydra.load.load`, what `make load`
  does). The next run must enqueue the same URLs again as fresh rows
  (`UNIQUE (run_id, ...)` scopes to the run), re-observe every product page,
  and write `unchanged` lightweight rows against run 1's priors (spec 003
  §4) under version-2 templates (ADR-0006).

The adapter level (`frontier.enqueue`'s conflict handling, the claim's
breadth-first order) is already pinned in `tests/adapters/postgres/`; what is
pinned here is the same behaviour arriving at the queue through a real crawl.
"""

from collections import Counter
from pathlib import Path
from subprocess import Popen
from urllib.parse import urlsplit

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.configuration import PostgresConfiguration
from spydra.domain.ids import RunId
from spydra.load import load
from tests.fixtures import catalogue
from tests.fixtures.catalogue import DEEP_PREFIX, EXIT_DISCOVERY, EXIT_SEED, PER_PAGE
from tests.fixtures.server import FixtureSite
from tests.scheduler.test_link_discovery import (
    LISTING_PATTERN,
    PRODUCT_PATTERN,
    is_facet,
    path_of,
    seed_halden,
)
from tests.scheduler.test_worker_process import rows, run_state, wait_until, worker

pytestmark = pytest.mark.integration

# The mega rule: EXIT_DISCOVERY with the subcategory selector widened onto
# the mega menu every page carries. Same deny (facets stay out only through
# it), same `product_links`, same `next_page` — only the discovery surface
# grows, so any row the crawl loses or duplicates is the dedupe's doing.
MEGA_DISCOVERY = EXIT_DISCOVERY | {
    "subcategory_links": "nav.mega a, section.subcategories a, form.facets a"
}


def _spellings(leaf: catalogue.Node) -> set[str]:
    """The queue spellings a leaf's listings link their products under: the
    category-context form for `context_links` leaves, the plain one
    otherwise — `catalogue._product_href`, read from the constants."""
    if leaf.context_links:
        return {f"{leaf.path}p/{sku}" for sku in leaf.skus}
    return {f"/shop/p/{sku}" for sku in leaf.skus}


def expected_queue(mega: bool) -> set[str]:
    """The canonical paths a crawl from `EXIT_SEED` must queue, derived from
    the catalogue constants so the test and the fixture cannot drift.

    `mega=False` is the 2.3 exit shape (44 rows: the cutting subtree, the
    depth chain, the featured product). `mega=True` adds the rest of the
    tree through the mega menu (84 rows). Both crawl the same seed; only the
    discovery rule differs.
    """
    nodes = [n for n in catalogue.NODES if mega or n.path.startswith(EXIT_SEED)]
    paths = {n.path.rstrip("/") for n in nodes}
    for leaf in (n for n in nodes if n.products):
        for page in range(2, -(-leaf.products // PER_PAGE) + 1):
            paths.add(f"{leaf.path.rstrip('/')}?page={page}")
        paths |= _spellings(leaf)
    # The depth chain hangs off the seed's own tiles; `/shop/deep/6/` is the
    # first page the domain's `max_depth = 5` must refuse.
    paths |= {f"{DEEP_PREFIX}{n}" for n in range(1, 6)}
    # The seed page features one product by its canonical spelling: a second
    # queue row for a page blades also link in context (2.2's pair).
    paths.add(catalogue.FEATURED[EXIT_SEED])
    return paths


async def wait_completed(
    engine: AsyncEngine,
    proc: Popen[bytes],
    log: Path,
    run: RunId,
    *,
    what: str,
) -> None:
    """Wait for the run to reach `completed` behind an already-running
    worker, politely: one connection, the per-domain gate, the 20 ms delay
    `seed_halden` sets."""

    async def completed() -> bool:
        return await run_state(engine, run) == "completed"

    await wait_until(completed, proc, log, timeout=120, what=what)


# ---------------------------------------------------------------------------
# 1. Within-run dedupe, through the worker — the mega crawl
# ---------------------------------------------------------------------------


async def test_a_url_re_discovered_from_every_page_enqueues_once_and_the_crawl_completes(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """The mega menu links every category on every page, so from the second
    listing onwards each category URL is a re-discovery. The constraint
    (`UNIQUE (run_id, url_hash)`, spec 001 §1) plus the guarded enqueue make
    each of them one row; a crawl that raised on the second spelling, or left
    duplicates' retries behind, fails here."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        base = site.base_url
        domain, run, _ = await seed_halden(engine, base, discovery=MEGA_DISCOVERY)
        with worker(database_url, log, WORKER_STATIC="1") as proc:
            await wait_completed(engine, proc, log, run, what="the mega crawl")
            proc.terminate()
            proc.wait(timeout=30)
        requested = [path for _, path in site.requests]

    own_host = urlsplit(base).netloc
    queue = await rows(
        engine,
        "SELECT url, depth, state FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id",
        r=int(run),
    )

    # Every row done, none failed, none left pending; the run and the domain
    # both finished healthy (ADR-0039: listings stayed out of the verdict).
    assert {r.state for r in queue} == {"done"}
    assert await run_state(engine, run) == "completed"
    assert (
        await rows(
            engine, "SELECT state::text AS s FROM crawl.domains WHERE id = :d", d=int(domain)
        )
    )[0].s == "active"

    # Exactly the mega shape, each URL once. The Counter is the dedupe: a
    # re-discovered spelling that slipped through would count twice, and a
    # lost one would miss the set.
    seen: Counter[str] = Counter(path_of(r.url) for r in queue)
    expected = expected_queue(mega=True)
    assert set(seen) == expected, (
        f"queue differs from the mega shape: missing {sorted(expected - set(seen))[:5]}, "
        f"extra {sorted(set(seen) - expected)[:5]}"
    )
    assert [p for p, n in seen.items() if n > 1] == [], "a URL was queued twice in one run"
    assert path_of(base + EXIT_SEED) in seen, "the seed itself was not queued"
    # Every category exactly once is `expected`'s node paths under this
    # assertion; said separately because it is the acceptance's own words.
    for node in catalogue.NODES:
        assert seen[node.path.rstrip("/")] == 1

    # The full catalogue, observed as product pages, each page once. Blades'
    # context spellings and the featured spelling collapse to one page row
    # each (2.2, rel=canonical) — 64 SKUs, 64 page rows.
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
        f"/shop/p/{sku}" for sku in catalogue.PRODUCTS
    )

    # The canonical pair: two queue rows, one page row. The queue hashes the
    # lexical URL, the page the canonical one, so both spellings fetch and
    # one page exists (2.2's collapse, not a dedupe failure).
    blades = catalogue.BY_PATH["/shop/cutting/blades/"]
    context = f"{blades.path}p/HT-SB-001"
    featured = catalogue.FEATURED[EXIT_SEED]
    assert seen[context] == 1 and seen[featured] == 1
    product_pages = await rows(
        engine,
        """
        SELECT p.url FROM crawl.pages p
        JOIN crawl.templates t ON t.id = p.template_id
        WHERE p.domain_id = :d AND t.page_kind = 'product'
        """,
        d=int(domain),
    )
    assert [r.url for r in product_pages if path_of(r.url) == featured] == [base + featured], (
        "the canonical pair produced more than one page row"
    )

    # The deny and the depth cap survive the wider rule: no facet URL and
    # nothing off-host in the queue or the request log, `/shop/deep/6/`
    # never queued, never requested.
    assert [r.url for r in queue if is_facet(r.url)] == []
    assert [p for p in requested if is_facet(p)] == []
    assert [r.url for r in queue if urlsplit(r.url).netloc != own_host] == []
    assert f"{DEEP_PREFIX}6" not in seen
    assert not any(p.rstrip("/") == f"{DEEP_PREFIX}6" for p in requested)
    assert max(r.depth for r in queue) == 5

    # Acceptance 3: breadth-first end to end. Every depth-1 URL is
    # discovered from the seed's own page, so once the worker moves on to
    # depth 2 no shallower row can appear behind it. `robots.txt` (and any
    # non-queue request) is filtered by the lookup.
    depth_of = {path_of(r.url): r.depth for r in queue}
    sequence = [depth_of[path_of(base + p)] for p in requested if path_of(base + p) in depth_of]
    assert sequence == sorted(sequence), "a shallower page was requested after a deeper one"


# ---------------------------------------------------------------------------
# 2. The re-crawl — a later run enqueues again, through apply
# ---------------------------------------------------------------------------


def _yaml(base: str) -> str:
    """The exit configuration as an operator's file: the fixture site's host,
    `EXIT_DISCOVERY`'s keys **minus `max_depth`** (the loader refuses it; the
    domain default is already 5), product extraction as 1.14's loader tests
    write it, listing extraction empty (ADR-0039)."""
    host = urlsplit(base).netloc
    return f"""
domains:
  - host: {host}
    scheme: http
    render_mode: static
    crawl_delay_ms: 20
    respect_robots: true
    templates:
      - name: halden listing
        url_pattern: '{LISTING_PATTERN}'
        page_kind: listing
        discovery:
          product_links: "a.product-card__link"
          next_page: "a[rel='next']"
          subcategory_links: "section.subcategories a, form.facets a"
          deny_patterns: ['[?&](colour|grit|sort|view|per_page)=']
        extraction: {{}}
      - name: halden product
        url_pattern: '{PRODUCT_PATTERN}'
        page_kind: product
        extraction:
          title: {{ selector: ".product__title", transform: [trim], validation: [non_empty] }}
          price: {{ selector: ".product__price", validation: [currency] }}
    seeds:
      - {base}{EXIT_SEED}
"""


async def test_a_second_load_recrawls_the_same_urls_as_fresh_unchanged_rows(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """Both runs through `PostgresConfiguration.apply` — the only production
    run-creation path, what a second `make load` does. Run 2 must be a new
    run whose queue equals run 1's as fresh rows (a dedupe made cross-run
    completes too, with one row, which is why the assertion is set
    equality), re-observe every product page, and write `unchanged` rows
    against run 1's priors (spec 003 §4) under version-2 templates
    (ADR-0006)."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        base = site.base_url
        yaml = _yaml(base)
        configuration = PostgresConfiguration(engine)
        run1 = await load(configuration, yaml)
        # One worker process serves both runs in sequence, as one worker
        # serves a domain's nightly re-crawl.
        with worker(database_url, log, WORKER_STATIC="1") as proc:
            await wait_completed(engine, proc, log, run1, what="run 1 to complete")
            run2 = await load(configuration, yaml)
            await wait_completed(engine, proc, log, run2, what="run 2 to complete")
            proc.terminate()
            proc.wait(timeout=30)

    assert int(run1) != int(run2), "the second apply did not start a new run"
    expected = expected_queue(mega=False)

    run1_rows = await rows(
        engine,
        "SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id",
        r=int(run1),
    )
    run2_rows = await rows(
        engine,
        "SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id",
        r=int(run2),
    )

    # Run 1's rows are untouched — still `done`, still under run 1 — and run
    # 2's are a fresh set with the same content: 44 new rows, none of them a
    # conflict away.
    assert {r.state for r in run1_rows} == {"done"}
    assert {path_of(r.url) for r in run1_rows} == expected
    assert {r.state for r in run2_rows} == {"done"}
    assert {path_of(r.url) for r in run2_rows} == expected, (
        "run 2's queue set differs from run 1's: a cross-run dedupe, or lost work"
    )

    # Every product page observed in run 1 is observed again in run 2: the
    # re-crawl re-observes, it does not skip.
    product_pages_1 = {
        r.id
        for r in await rows(
            engine,
            """
            SELECT DISTINCT p.id FROM crawl.pages p
            JOIN crawl.templates t ON t.id = p.template_id
            JOIN crawl.page_observations o ON o.page_id = p.id AND o.run_id = :r
            WHERE t.page_kind = 'product'
            """,
            r=int(run1),
        )
    }
    assert len(product_pages_1) == len(catalogue.products_under(EXIT_SEED))
    run2_products = await rows(
        engine,
        """
        SELECT o.page_id, o.template_id, o.unchanged, o.empty_extraction,
               o.title, o.price_amount, o.content_hash
        FROM crawl.page_observations o
        JOIN crawl.templates t ON t.id = o.template_id
        WHERE o.run_id = :r AND t.page_kind = 'product'
        """,
        r=int(run2),
    )
    assert {r.page_id for r in run2_products} == product_pages_1

    # Spec 003 §4: the fixture is deterministic, so run 2's digest matches
    # run 1's prior — which is looked up across runs — and the row is the
    # lightweight one: hash kept, fields not repeated, emptiness still
    # decided from the real extraction, never from the emptied fields.
    assert all(r.unchanged for r in run2_products), "run 2 re-hashed instead of comparing"
    assert all(r.content_hash is not None for r in run2_products)
    assert all(r.title is None and r.price_amount is None for r in run2_products)
    assert all(not r.empty_extraction for r in run2_products)

    # The second apply versioned the templates (v1 → v2, v1 inactive) and
    # every observation names its own run's version (AGENTS.md rule 12).
    templates = await rows(
        engine,
        "SELECT id, url_pattern, version, is_active FROM crawl.templates ORDER BY id",
    )
    assert {(r.url_pattern, r.version) for r in templates} == {
        (LISTING_PATTERN, 1),
        (LISTING_PATTERN, 2),
        (PRODUCT_PATTERN, 1),
        (PRODUCT_PATTERN, 2),
    }
    assert all((r.version == 2) == r.is_active for r in templates)
    v1 = {r.id for r in templates if r.version == 1}
    v2 = {r.id for r in templates if r.version == 2}
    named = {
        r.template_id
        for r in await rows(
            engine,
            "SELECT DISTINCT template_id FROM crawl.page_observations"
            " WHERE run_id = :r AND template_id IS NOT NULL",
            r=int(run1),
        )
    }
    assert named == v1, "run 1's observations do not name the v1 templates"
    named2 = {
        r.template_id
        for r in await rows(
            engine,
            "SELECT DISTINCT template_id FROM crawl.page_observations"
            " WHERE run_id = :r AND template_id IS NOT NULL",
            r=int(run2),
        )
    }
    assert named2 == v2, "run 2's observations do not name the v2 templates"

    # The domain stayed `active` throughout: an `apply` on a live domain
    # versions templates and starts a run, and never resets politeness state.
    domain = (await rows(engine, "SELECT domain_ids FROM crawl.runs WHERE id = :r", r=int(run1)))[
        0
    ].domain_ids[0]
    assert (
        await rows(
            engine, "SELECT state::text AS s FROM crawl.domains WHERE id = :d", d=int(domain)
        )
    )[0].s == "active"
