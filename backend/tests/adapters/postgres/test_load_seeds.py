"""The CSV seed loader against real Postgres and the real worker (BUILD_PLAN
2.9, spec 004 §6).

Committed rows (`clean_crawl`), for the same reason as the YAML loader's
suite: `PostgresConfiguration.apply` opens its own transaction, and the
partial-import and refusal tests are about what that transaction leaves
behind when a row or the world refuses it.

What is held:

- **The done-when, literally.** A file with one bad row imports the rest —
  domains, seeds and run verified by row counts, including the row AFTER
  the bad one — and the failure is named with its file line and reason.
- **Rejects never reach `apply`.** An all-rejected or header-only file
  writes nothing and starts no run (`run_id is None`); a bad header
  refuses before a transaction opens.
- **Template-less domains through the real `apply`**: land `active` with
  the file's settings, no template rows, one run per file covering
  exactly the file's domains, seeds enqueued at depth 0. A reload re-seeds
  an existing `active` domain into a new run and updates its settings.
- **The template-less crawl, end to end**: a CSV seed against the fixture
  site (loopback), crawled by the real worker process — the run crawls
  exactly the file's seeds and drains (no discovery expansion), every 200
  is an `unknown_pages` row saying `no_template`, the domain never moves,
  the run completes.
- **The world-conflict refusal** carried from the YAML loader: a domain
  already `paused`/`broken`/`archived` refuses the whole file, nothing
  written.
- **The CLI's exit contract**, as `make load-seeds` runs it.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.configuration import PostgresConfiguration
from spydra.domain.errors import RefusedConfiguration
from spydra.domain.urls import canonical_url
from spydra.load_seeds import load
from tests.conftest import BACKEND_ROOT
from tests.fixtures.server import FixtureSite
from tests.scheduler.test_worker_process import rows, run_state, wait_until, worker

pytestmark = pytest.mark.integration

_GOOD = (
    "host,seed_url\n"
    "shop.test:8099,http://shop.test:8099/p/one\n"
    "shop.test:8099,http://shop.test:8099/p/two\n"
    "plain.test,https://plain.test/item/three\n"
)

# The done-when's bad row sits BETWEEN valid rows, so a loader that aborted
# at the first reject loses line 4 too.
_ONE_BAD_ROW = (
    "host,seed_url\n"
    "shop.test:8099,http://shop.test:8099/p/one\n"
    "plain.test,https://elsewhere.test/item/three\n"  # line 3 — host_mismatch
    "shop.test:8099,http://shop.test:8099/p/two\n"  # line 4 — still imports
)

_ALL_REJECTED = "host,seed_url\nplain.test,https://elsewhere.test/item/three\n"

_HEADER_ONLY = "host,seed_url\n"

_BAD_HEADER = "seed_url,host\nshop.test:8099,http://shop.test:8099/p/one\n"

_NOTHING = {"domains": 0, "templates": 0, "runs": 0, "queue": 0}


async def _counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                sa.text(
                    """
SELECT (SELECT count(*) FROM crawl.domains)     AS domains,
       (SELECT count(*) FROM crawl.templates)   AS templates,
       (SELECT count(*) FROM crawl.runs)        AS runs,
       (SELECT count(*) FROM crawl.crawl_queue) AS queue
"""
                )
            )
        ).one()
    return dict(row._mapping)


async def _domain(engine: AsyncEngine, host: str) -> sa.RowMapping:
    async with engine.connect() as conn:
        return (
            (
                await conn.execute(
                    sa.text(
                        "SELECT id, state::text AS state, render_mode, crawl_delay_ms,"
                        " configured_crawl_delay_ms, respect_robots"
                        " FROM crawl.domains WHERE host = :h"
                    ),
                    {"h": host},
                )
            )
            .mappings()
            .one()
        )


# ---------------------------------------------------------------------------
# The done-when: one bad row imports the rest and names the failure
# ---------------------------------------------------------------------------


async def test_a_file_with_one_bad_row_imports_the_rest_and_starts_the_run(
    clean_crawl: AsyncEngine,
) -> None:
    result = await load(PostgresConfiguration(clean_crawl), _ONE_BAD_ROW)

    assert result.run_id is not None
    (reject,) = result.seed_file.rejects
    assert (reject.line, reject.token) == (3, "host_mismatch")
    # The valid rows — line 4 included — are written: 1 domain, 2 seeds, 1 run.
    assert await _counts(clean_crawl) == {"domains": 1, "templates": 0, "runs": 1, "queue": 2}


async def test_a_good_file_imports_every_row(clean_crawl: AsyncEngine) -> None:
    result = await load(PostgresConfiguration(clean_crawl), _GOOD)

    assert result.run_id is not None
    assert result.seed_file.rejects == ()
    assert await _counts(clean_crawl) == {"domains": 2, "templates": 0, "runs": 1, "queue": 3}


# ---------------------------------------------------------------------------
# Rejects never reach apply: nothing written, no empty run
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "rejected"),
    [(_ALL_REJECTED, True), (_HEADER_ONLY, False)],
    ids=["every-row-rejected", "header-only"],
)
async def test_a_file_with_nothing_to_import_writes_nothing_and_starts_no_run(
    clean_crawl: AsyncEngine, text: str, rejected: bool
) -> None:
    result = await load(PostgresConfiguration(clean_crawl), text)

    assert result.run_id is None
    assert bool(result.seed_file.rejects) is rejected
    assert await _counts(clean_crawl) == _NOTHING


async def test_a_bad_header_refuses_before_any_transaction_opens(clean_crawl: AsyncEngine) -> None:
    with pytest.raises(ValueError, match="header must be"):
        await load(PostgresConfiguration(clean_crawl), _BAD_HEADER)

    assert await _counts(clean_crawl) == _NOTHING


# ---------------------------------------------------------------------------
# Template-less domains through the real apply
# ---------------------------------------------------------------------------


async def test_a_template_less_domain_lands_active_with_the_files_settings(
    clean_crawl: AsyncEngine,
) -> None:
    result = await load(PostgresConfiguration(clean_crawl), _GOOD)

    assert result.run_id is not None
    shop = await _domain(clean_crawl, "shop.test:8099")
    plain = await _domain(clean_crawl, "plain.test")
    for row in (shop, plain):
        assert row["state"] == "active"
        assert row["render_mode"] == "static"
        assert row["respect_robots"] is True
        assert row["crawl_delay_ms"] == row["configured_crawl_delay_ms"] == 2000

    # No template rows, ever: a CSV cannot express one (ADR-0006).
    async with clean_crawl.connect() as conn:
        (templates,) = (
            await conn.execute(sa.text("SELECT count(*) FROM crawl.templates"))
        ).scalars()
        (run_domains,) = (
            await conn.execute(
                sa.text("SELECT domain_ids FROM crawl.runs WHERE id = :r"),
                {"r": int(result.run_id)},
            )
        ).scalars()
        queue = (
            (
                await conn.execute(
                    sa.text(
                        "SELECT domain_id, url, depth FROM crawl.crawl_queue"
                        " WHERE run_id = :r ORDER BY id"
                    ),
                    {"r": int(result.run_id)},
                )
            )
            .mappings()
            .all()
        )
    assert templates == 0
    assert sorted(run_domains) == sorted([shop["id"], plain["id"]])
    assert [(q["domain_id"], q["url"], q["depth"]) for q in queue] == [
        (shop["id"], "http://shop.test:8099/p/one", 0),
        (shop["id"], "http://shop.test:8099/p/two", 0),
        (plain["id"], "https://plain.test/item/three", 0),
    ]


async def test_reloading_re_seeds_the_active_domain_into_a_new_run_and_updates_settings(
    clean_crawl: AsyncEngine,
) -> None:
    configuration = PostgresConfiguration(clean_crawl)
    first = await load(configuration, _GOOD)

    second = await load(
        configuration,
        "host,seed_url,render_mode,crawl_delay_ms\n"
        "shop.test:8099,http://shop.test:8099/p/one,rendered,7000\n",
    )

    assert second.run_id is not None and second.run_id != first.run_id
    # The domain is updated, not duplicated, and re-seeded into the new run.
    assert await _counts(clean_crawl) == {"domains": 2, "templates": 0, "runs": 2, "queue": 4}
    shop = await _domain(clean_crawl, "shop.test:8099")
    assert shop["state"] == "active"
    assert shop["render_mode"] == "rendered"
    assert shop["configured_crawl_delay_ms"] == 7000
    async with clean_crawl.connect() as conn:
        second_queue = (
            await conn.execute(
                sa.text("SELECT count(*) FROM crawl.crawl_queue WHERE run_id = :r"),
                {"r": int(second.run_id)},
            )
        ).scalar_one()
    assert second_queue == 1


# ---------------------------------------------------------------------------
# The world-conflict refusal, carried from the YAML loader
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", ["paused", "broken", "archived"])
async def test_a_domain_in_a_state_a_file_cannot_approve_refuses_the_whole_file(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """A conflict with the world, not with a row's syntax: the transaction
    rolls back the whole file, and the operator removes that host's rows."""
    configuration = PostgresConfiguration(clean_crawl)
    await load(configuration, _GOOD)
    async with clean_crawl.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE crawl.domains SET state = CAST(:s AS crawl.domain_state)"
                " WHERE host = 'shop.test:8099'"
            ),
            {"s": state},
        )
    before = await _counts(clean_crawl)

    with pytest.raises(RefusedConfiguration, match=state):
        await load(configuration, _GOOD)

    assert await _counts(clean_crawl) == before


# ---------------------------------------------------------------------------
# The template-less crawl, end to end: the real worker against the fixture site
# ---------------------------------------------------------------------------


async def test_a_template_less_seed_run_crawls_exactly_the_seed_and_completes(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """The contract's Halden path through the real `apply` and the real
    worker. `/shop/cutting/` links the whole catalogue tree — mega menu,
    pagination, facets — so a queue of exactly one row closed `done` is the
    proof discovery never expanded; the inbox row is the product: "give
    these domains templates"."""
    engine = clean_crawl
    log = tmp_path / "worker.log"
    with FixtureSite() as site:
        host = urlsplit(site.base_url).netloc
        seed = f"{site.base_url}/shop/cutting/"
        result = await load(
            PostgresConfiguration(engine),
            f"host,seed_url,render_mode,crawl_delay_ms\n{host},{seed},static,20\n",
        )
        assert result.run_id is not None
        run = result.run_id

        with worker(database_url, log, WORKER_STATIC="1") as proc:

            async def completed() -> bool:
                return await run_state(engine, run) == "completed"

            await wait_until(completed, proc, log, timeout=60, what="the seed-only run to drain")

        # Crawled exactly the seed: one queue row, closed done, no expansion.
        queue = await rows(
            engine,
            "SELECT url, state FROM crawl.crawl_queue WHERE run_id = :r ORDER BY id",
            r=int(run),
        )
        assert [(q.url, q.state) for q in queue] == [(seed, "done")]

        # Every 200 is one inbox row saying what is missing, on no one's
        # evidence but the page's own.
        unknown = await rows(engine, "SELECT url, reason FROM crawl.unknown_pages")
        assert [(u.url, u.reason) for u in unknown] == [(canonical_url(seed), "no_template")]

        # The structured rung still ran without a template, so the crawl is
        # an observation, not a no-op.
        observations = await rows(
            engine,
            "SELECT http_status FROM crawl.page_observations WHERE run_id = :r",
            r=int(run),
        )
        assert [o.http_status for o in observations] == [200]

        # The domain never moved: template-less pages are a configuration
        # gap, not evidence against the domain (ADR-0030).
        (domain,) = await rows(engine, "SELECT state::text AS s FROM crawl.domains")
        assert domain.s == "active"

        # And the site saw one page request, robots aside.
        crawled = [path for _, path in site.requests if path != "/robots.txt"]
        assert crawled == ["/shop/cutting/"]


# ---------------------------------------------------------------------------
# The CLI, as `make load-seeds` runs it
# ---------------------------------------------------------------------------


def _cli(database_url: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "spydra.load_seeds", str(path)],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


async def test_the_cli_imports_a_good_file_and_exits_zero(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    path = tmp_path / "seeds.csv"
    path.write_text(_GOOD, encoding="utf-8")

    done = _cli(database_url, path)

    assert done.returncode == 0, done.stderr
    assert done.stderr == ""
    assert "2 domains, 3 seeds imported" in done.stdout
    assert "started from" in done.stdout
    assert await _counts(clean_crawl) == {"domains": 2, "templates": 0, "runs": 1, "queue": 3}


async def test_the_cli_imports_the_rest_reports_the_reject_and_exits_one(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """An exit code is the only channel `make` has, and "imported with
    rejections" is not success. The valid rows still imported."""
    path = tmp_path / "one-bad-row.csv"
    path.write_text(_ONE_BAD_ROW, encoding="utf-8")

    done = _cli(database_url, path)

    assert done.returncode == 1
    assert "line 3: host_mismatch" in done.stderr
    assert "1 domain, 2 seeds imported" in done.stdout
    assert "started from" in done.stdout
    assert await _counts(clean_crawl) == {"domains": 1, "templates": 0, "runs": 1, "queue": 2}


async def test_the_cli_refuses_a_bad_header_exiting_one_with_nothing_written(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    path = tmp_path / "bad-header.csv"
    path.write_text(_BAD_HEADER, encoding="utf-8")

    done = _cli(database_url, path)

    assert done.returncode == 1
    assert "refused:" in done.stderr
    assert "header must be" in done.stderr
    assert await _counts(clean_crawl) == _NOTHING


async def test_the_cli_refuses_an_all_rejected_file_but_still_prints_the_rejects(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    """The rejects must reach the operator even when nothing was written —
    an exception from inside `load` would strand them."""
    path = tmp_path / "all-rejected.csv"
    path.write_text(_ALL_REJECTED, encoding="utf-8")

    done = _cli(database_url, path)

    assert done.returncode == 1
    assert "line 2: host_mismatch" in done.stderr
    assert "refused: every row was rejected" in done.stderr
    assert await _counts(clean_crawl) == _NOTHING


async def test_the_cli_refuses_a_header_only_file(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    path = tmp_path / "header-only.csv"
    path.write_text(_HEADER_ONLY, encoding="utf-8")

    done = _cli(database_url, path)

    assert done.returncode == 1
    assert "refused: no data rows" in done.stderr
    assert await _counts(clean_crawl) == _NOTHING
