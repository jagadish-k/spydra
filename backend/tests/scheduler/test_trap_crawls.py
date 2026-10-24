"""The trap defences at crawl size, through the real worker (BUILD_PLAN 2.5,
spec 004 §3, §5; ADR-0040).

**Terminated by a named defence, not by the fixture running out.** The unit
level (`tests/discovery/test_trap_rejects.py`) proves each reject fires with
a reason, a count and a sample; these crawls prove the same defences are
what ends the trap at run size — the loop crawl queues exactly two hops of
the relative-link bug and the single-segment trap exactly two `deeper`s,
and neither run finishes because the site stopped answering.

The fourth crawl is ADR-0040's own acceptance: a facet explosion with the
deny dropped and a low `url_cap` breaches, the run is **failed** with the
cap named as the reason — never a clean finish — the domain stays
`active`, and the next run on the same domain starts clean under the same
cap because the count is per `(run, domain)`.

All four run the `seed_halden` substrate: one connection, the per-domain
gate, `crawl_delay_ms = 20`.
"""

import json
from collections.abc import Callable
from pathlib import Path
from subprocess import Popen
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

import spydra.scheduler.crawl as crawl_module
from spydra.adapters.clock import SystemClock
from spydra.adapters.http.httpx_fetcher import HttpxFetcher
from spydra.adapters.postgres.configuration import PostgresConfiguration
from spydra.adapters.postgres.frontier import PostgresFrontier, url_hash
from spydra.domain.ids import RunId
from spydra.load import load
from tests.fixtures.catalogue import EXIT_DISCOVERY, EXIT_SEED
from tests.fixtures.server import FixtureSite
from tests.scheduler.test_canonical_pages import build, make_due
from tests.scheduler.test_dedupe_recrawl import expected_queue, wait_completed
from tests.scheduler.test_link_discovery import (
    LISTING_PATTERN,
    PRODUCT_PATTERN,
    path_of,
    seed_halden,
)
from tests.scheduler.test_worker_process import rows, run_state, wait_until, worker

pytestmark = pytest.mark.integration

# The footer is on every Halden listing page but `EXIT_DISCOVERY` alone does
# not reach it — the trap tests widen the rule, 2.3's established pattern.
FOOTER_DISCOVERY = EXIT_DISCOVERY | {
    "subcategory_links": "section.subcategories a, form.facets a, footer.site-footer a"
}

TRAP_SEED = "/trap/"
BREACH_CAP = 200


async def domain_state(engine: AsyncEngine, domain: int) -> str:
    return str(
        (await rows(engine, "SELECT state::text AS s FROM crawl.domains WHERE id = :d", d=domain))[
            0
        ].s
    )


async def queue_of(engine: AsyncEngine, run: int) -> dict[str, tuple[str, int, str]]:
    """Canonical path → (url, depth, state) for one run's rows."""
    return {
        path_of(r.url): (r.url, r.depth, r.state)
        for r in await rows(
            engine,
            "SELECT url, depth, state FROM crawl.crawl_queue WHERE run_id = :r",
            r=run,
        )
    }


async def wait_failed(
    engine: AsyncEngine, proc: Popen[bytes], log: Path, run: RunId, *, what: str
) -> None:
    async def failed() -> bool:
        return await run_state(engine, run) == "failed"

    await wait_until(failed, proc, log, timeout=180, what=what)


# ---------------------------------------------------------------------------
# 1. The loop, the calendar and the long link — one footer-reachable crawl
# ---------------------------------------------------------------------------


async def test_a_footer_reachable_crawl_terminates_the_three_link_traps(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """From the exit seed with the footer reachable: the relative-link loop
    is enqueued at hop one and hop two, crawled both, and never a third —
    `repeating_path` refused it; the calendar is queued zero times; and no
    queue URL is over 2,000 characters. The run completes: every trap was
    stopped by a defence, not by the crawl dying."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        base = site.base_url
        domain, run, _ = await seed_halden(engine, base, discovery=FOOTER_DISCOVERY)
        with worker(database_url, log, WORKER_STATIC="1") as proc:
            await wait_completed(engine, proc, log, run, what="the footer crawl")
            proc.terminate()
            proc.wait(timeout=30)
        requested = [path for _, path in site.requests]

    queued = await queue_of(engine, int(run))

    # The loop: two hops enqueued and crawled done; no row anywhere carries a
    # third `loop/x` unit — that link exists on the hop-two page, so only a
    # defence refused it.
    assert (queued["/shop/loop/x/page"][1], queued["/shop/loop/x/page"][2]) == (1, "done")
    assert (queued["/shop/loop/x/loop/x/page"][1], queued["/shop/loop/x/loop/x/page"][2]) == (
        2,
        "done",
    )
    assert all(url.count("/loop/x/") <= 2 for url, _, _ in queued.values()), (
        "a third loop unit reached the queue"
    )
    assert any(p.rstrip("/").endswith("/loop/x/page") for p in requested)

    # The calendar: the footer links `/shop/news/2026/10/` on every listing
    # page; zero of them queued, none requested.
    assert not [p for p in queued if p.startswith("/shop/news/")]
    assert not [p for p in requested if "/shop/news/" in p]

    # The long link: the footer's 2,100-character search URL never queued.
    assert all(len(url) <= 2000 for url, _, _ in queued.values())

    assert {state for _, _, state in queued.values()} == {"done"}
    assert await run_state(engine, run) == "completed"
    assert await domain_state(engine, int(domain)) == "active"


# ---------------------------------------------------------------------------
# 2. The single-segment trap (1.4's /trap/)
# ---------------------------------------------------------------------------


async def test_a_crawl_seeded_on_the_single_segment_trap_stops_at_two_hops(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """/trap/ links `/trap/deeper/`, which links `/trap/deeper/deeper/`,
    which links one more. A crawl seeded there with a rule matching `a`
    queues at most two hops — the third is `deeper` ×3, and the run
    completes over exactly the three honest pages."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        domain, run, _ = await seed_halden(
            engine,
            site.base_url,
            seed=TRAP_SEED,
            listing_pattern=r"^/trap(/|$)",
            discovery={"subcategory_links": "a"},
        )
        with worker(database_url, log, WORKER_STATIC="1") as proc:
            await wait_completed(engine, proc, log, run, what="the trap crawl")
            proc.terminate()
            proc.wait(timeout=30)

    queued = await queue_of(engine, int(run))
    assert set(queued) == {"/trap", "/trap/deeper", "/trap/deeper/deeper"}
    assert "/trap/deeper/deeper/deeper" not in queued
    assert {state for _, _, state in queued.values()} == {"done"}
    assert await run_state(engine, run) == "completed"
    assert await domain_state(engine, int(domain)) == "active"


# ---------------------------------------------------------------------------
# 3. The cap breach, and the next run starting clean (ADR-0040)
# ---------------------------------------------------------------------------


def _yaml(base: str, *, deny: bool) -> str:
    """The exit configuration as an operator's file (`test_dedupe_recrawl`'s
    shape), with the facet deny the one toggle: `deny=False` is the
    operator's mistake that walks the crawl into the facet space."""
    host = urlsplit(base).netloc
    discovery: dict[str, object] = {
        "product_links": "a.product-card__link",
        "next_page": "a[rel='next']",
        "subcategory_links": "section.subcategories a, form.facets a",
    }
    if deny:
        discovery["deny_patterns"] = [r"[?&](colour|grit|sort|view|per_page)="]
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
        discovery: {json.dumps(discovery)}
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


async def test_a_cap_breach_fails_the_run_with_the_cap_named_and_the_next_run_is_clean(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """Run 1 walks into the facet space (deny dropped) under a low cap, set
    by SQL the way the planner does. It must end `failed` with `stop_reason`
    naming the cap and the host, its pending rows abandoned and counted in
    `stats.pages_abandoned`, the domain still `active`, and no row deleted.
    Run 2 — the deny restored by a second `apply`, the same low cap —
    completes over the whole exit shape, which is only possible if its
    count started from zero."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        base = site.base_url
        host = urlsplit(base).netloc
        configuration = PostgresConfiguration(engine)
        run1 = await load(configuration, _yaml(base, deny=False))
        async with engine.begin() as conn:
            await conn.execute(
                sa.text("UPDATE crawl.domains SET url_cap = :cap WHERE host = :h"),
                {"cap": BREACH_CAP, "h": host},
            )
        with worker(database_url, log, WORKER_STATIC="1") as proc:
            await wait_failed(engine, proc, log, run1, what="the breach to fail the run")

            async def drained() -> bool:
                return not await rows(
                    engine,
                    "SELECT 1 FROM crawl.crawl_queue "
                    "WHERE run_id = :r AND state IN ('pending', 'in_flight')",
                    r=int(run1),
                )

            await wait_until(drained, proc, log, timeout=60, what="the in-flight tail to drain")

            run2 = await load(configuration, _yaml(base, deny=True))
            await wait_completed(engine, proc, log, run2, what="the next run to complete")
            proc.terminate()
            proc.wait(timeout=30)

    domain = (await rows(engine, "SELECT domain_ids FROM crawl.runs WHERE id = :r", r=int(run1)))[
        0
    ].domain_ids[0]
    breach = (
        await rows(
            engine,
            "SELECT state::text AS s, stop_reason, finished_at, stats"
            " FROM crawl.runs WHERE id = :r",
            r=int(run1),
        )
    )[0]

    # Never a clean finish: terminal `failed` AND the named reason AND the
    # abandoned count, together (ADR-0040).
    assert breach.s == "failed"
    assert breach.stop_reason == f"url cap exceeded: {BREACH_CAP} urls queued for {host}"
    assert breach.finished_at is not None
    assert breach.stats["pages_abandoned"] > 0

    run1_rows = await rows(
        engine, "SELECT state FROM crawl.crawl_queue WHERE run_id = :r", r=int(run1)
    )
    states = {r.state for r in run1_rows}
    assert "pending" not in states, "the halt left work the run would wait on for ever"
    assert "abandoned" in states
    assert len(run1_rows) >= BREACH_CAP, "the cap was never reached; this was not a breach"

    # The domain is untouched — run-scoped by design — and stays so.
    assert await domain_state(engine, domain) == "active"

    # The next run starts clean: under the SAME cap it queues the whole exit
    # shape as fresh rows, which a count that carried across runs would
    # refuse, and it completes.
    assert await run_state(engine, run2) == "completed"
    clean = (
        await rows(engine, "SELECT stop_reason, stats FROM crawl.runs WHERE id = :r", r=int(run2))
    )[0]
    assert clean.stop_reason is None
    assert clean.stats["pages_abandoned"] == 0
    queued = await queue_of(engine, int(run2))
    assert set(queued) == expected_queue(mega=False)
    assert {state for _, _, state in queued.values()} == {"done"}

    # No row was deleted: run 1's rows all still exist, still under run 1.
    after = await rows(
        engine, "SELECT count(*) AS n FROM crawl.crawl_queue WHERE run_id = :r", r=int(run1)
    )
    assert after[0].n == len(run1_rows)
    assert await domain_state(engine, domain) == "active"

    # Spec 009 §1 via ADR-0040: exactly one error line — the one caller that
    # transitioned the run; the bounded in-flight tail logs at debug.
    lines = [line for line in log.read_text().splitlines() if "url_cap_exceeded" in line]
    assert len(lines) == 1, lines

    # 2.8: the halt replayed — one `failed` `run_state` row carrying the
    # cap reason the operator reads and the same transition-time snapshot
    # `runs.stats` holds. It is followed only by the in-flight tail's page
    # events (ADR-0040's bounded tail closes on the failed run), never
    # another transition.
    halted_events = await rows(
        engine,
        "SELECT seq, kind, payload FROM crawl.run_events WHERE run_id = :r ORDER BY seq",
        r=int(run1),
    )
    halted_run_states = [dict(r.payload) for r in halted_events if r.kind == "run_state"]
    assert [p["state"] for p in halted_run_states] == ["failed"]
    assert halted_run_states[0]["stop_reason"] == breach.stop_reason
    assert halted_run_states[0]["stats"]["pages_abandoned"] == breach.stats["pages_abandoned"]
    # The mass abandon is a number, not a burst: no page event for any of
    # the rows the halt abandoned — only the pages that really closed,
    # including the bounded tail that finished after the halt.
    assert len([r for r in halted_events if r.kind == "page"]) == len(
        [r for r in run1_rows if r.state == "done"]
    )


# ---------------------------------------------------------------------------
# 4. First-signaller-wins, one claim at a time (ADR-0040's in-flight tail)
# ---------------------------------------------------------------------------


class LogRecorder:
    """Stands in for the module's structlog logger: level → list of events.

    The level is the contract under test (the re-signal logs at debug, not
    error — spec 009 §1), and the process's structlog is unconfigured, so
    there is no level in its rendered output to assert on. Recording the
    call instead pins exactly what ADR-0040 states.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def record(event: str, **_: object) -> None:
            self.calls.append((level, event))

        return record


async def test_only_the_signaller_that_transitions_the_run_logs_an_error(
    clean_crawl: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two pages claimed before either crawls (the domain's concurrency
    raised to 2), a cap of 3 against a queue already holding the two seed
    rows: the first page's discovery breaches (its batch inserts three new
    rows — the fourth link is the other seed, a conflict), halts and fails
    the run with one error line. The second page, still in flight,
    discovers, is refused, re-signals and transitions nothing: its
    `halt_run` matches no `running` row, and its line is at debug. The
    recording — state, reason, abandoned count — is the first signaller's
    alone."""
    recorder = LogRecorder()
    monkeypatch.setattr(crawl_module, "log", recorder)

    engine = clean_crawl
    with FixtureSite() as site:
        base = site.base_url
        host = urlsplit(base).netloc
        domain, run, _ = await seed_halden(engine, base)
        async with engine.begin() as conn:
            # A second seed row (the discs leaf), and room for both pages to
            # be in flight at once — the halt must leave in-flight rows alone.
            await conn.execute(
                sa.text(
                    "INSERT INTO crawl.crawl_queue (run_id, domain_id, url, url_hash, depth) "
                    "VALUES (:r, :d, :u, :h, 0)"
                ),
                {
                    "r": int(run),
                    "d": int(domain),
                    "u": base + "/shop/cutting/discs/",
                    "h": url_hash(base + "/shop/cutting/discs/"),
                },
            )
            await conn.execute(
                sa.text("UPDATE crawl.domains SET url_cap = 3, max_concurrency = 2 WHERE id = :d"),
                {"d": int(domain)},
            )

        await make_due(engine, domain)
        frontier = PostgresFrontier(engine)
        first = await frontier.claim()
        second = await frontier.claim()
        assert first is not None and second is not None

        static = HttpxFetcher(SystemClock())
        try:
            await build(engine, static).crawl(first)  # breaches: 4 links over a cap of 3
            await build(engine, static).crawl(second)  # refused, re-signals
        finally:
            await static.aclose()

    errors = [event for level, event in recorder.calls if level == "error"]
    debugs = [event for level, event in recorder.calls if level == "debug"]
    assert errors == ["url_cap_exceeded"], recorder.calls
    assert "url_cap_exceeded" in debugs, "the re-signal did not happen; the setup raced"

    breach = (
        await rows(
            engine,
            "SELECT state::text AS s, stop_reason, stats FROM crawl.runs WHERE id = :r",
            r=int(run),
        )
    )[0]
    assert breach.s == "failed"
    assert breach.stop_reason == f"url cap exceeded: 3 urls queued for {host}"
    assert breach.stats["pages_abandoned"] == 3, "the halt's abandon missed the new rows"

    states = await rows(engine, "SELECT state FROM crawl.crawl_queue WHERE run_id = :r", r=int(run))
    assert {r.state for r in states} == {"done", "abandoned"}
    assert await domain_state(engine, int(domain)) == "active"
