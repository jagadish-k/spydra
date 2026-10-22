"""The YAML loader against real Postgres (BUILD_PLAN 1.14).

Committed rows, so `clean_crawl`: `PostgresConfiguration` opens its own
transaction, and the atomicity tests are about what that transaction leaves
behind when it fails, which a rolled-back test transaction would hide.

What is held:

- `required: true` writes nothing at all (ADR-0027).
- A valid file writes what it says, as bytes the worker's codec reads back
  to the same rules (spec 013 §2).
- Loading again versions templates rather than editing them (AGENTS.md rule
  12, ADR-0006), updates domains rather than duplicating them, and starts a
  new run.
- A file that fails part-way writes nothing, not even the domains before
  the failure.
- `python -m spydra.load`, as the operator and `make phase1-exit` run it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.configuration import PostgresConfiguration
from spydra.adapters.postgres.templates import PostgresTemplates
from spydra.domain.entities import FieldRule, Rule, Transform
from spydra.domain.enums import PageKind, RuleName, TransformName
from spydra.domain.ids import DomainId
from spydra.load import RefusedConfiguration, load
from tests.conftest import BACKEND_ROOT

pytestmark = pytest.mark.integration

_VALID = """
domains:
  - host: shop.test:8099
    scheme: http
    render_mode: auto
    crawl_delay_ms: 5000
    respect_robots: false
    templates:
      - name: product
        url_pattern: "/p/.+"
        page_kind: product
        extraction:
          title: { selector: ".t", transform: [trim], validation: [non_empty] }
          specs:
            selector: ".specs tr"
            many: true
            transform: [{ name: pairs, args: [th, td] }]
            validation: [{ name: min_count, arg: 3 }]
          price: { selector: ".price", fallback: "[itemprop=price]", required: false }
      - name: listing
        url_pattern: "/c/.+"
        page_kind: listing
        extraction:
          title: { selector: "h1" }
    seeds:
      - /p/one
      - http://shop.test:8099/p/two
  - host: plain.test
    render_mode: static
    crawl_delay_ms: 2500
    templates:
      - name: product
        url_pattern: "/item/.+"
        extraction:
          title: { selector: ".name" }
    seeds: [/item/three]
"""

_SHOP_PRODUCT = {
    "title": FieldRule(
        selector=".t",
        transform=(Transform(TransformName.TRIM),),
        validation=(Rule(RuleName.NON_EMPTY),),
    ),
    "specs": FieldRule(
        selector=".specs tr",
        many=True,
        transform=(Transform(TransformName.PAIRS, ("th", "td")),),
        validation=(Rule(RuleName.MIN_COUNT, 3),),
    ),
    "price": FieldRule(selector=".price", fallback="[itemprop=price]"),
}


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


_NOTHING = {"domains": 0, "templates": 0, "runs": 0, "queue": 0}


async def _domains(engine: AsyncEngine) -> dict[str, sa.RowMapping]:
    async with engine.connect() as conn:
        rows = (
            (
                await conn.execute(
                    sa.text(
                        "SELECT id, host, state::text AS state, render_mode, crawl_delay_ms,"
                        " configured_crawl_delay_ms, respect_robots FROM crawl.domains"
                    )
                )
            )
            .mappings()
            .all()
        )
    return {row["host"]: row for row in rows}


async def _templates(engine: AsyncEngine) -> list[sa.RowMapping]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT id, domain_id, name, url_pattern, version, is_active, extraction"
                        " FROM crawl.templates ORDER BY id"
                    )
                )
            )
            .mappings()
            .all()
        )


# ---------------------------------------------------------------------------
# ADR-0027: refused, and nothing written
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # On a field of the SECOND domain, so a loader that wrote the first
        # domain before reaching it is caught.
        _VALID.replace(
            'title: { selector: ".name" }', 'title: { selector: ".name", required: true }'
        ),
        # One level off, on a template.
        _VALID.replace("name: listing\n", "name: listing\n        required: true\n"),
        # Inside a list.
        _VALID.replace("transform: [trim]", "transform: [{ name: trim, required: true }]"),
    ],
    ids=["field-second-domain", "template", "inside-a-list"],
)
async def test_required_true_is_refused_and_nothing_is_written(
    clean_crawl: AsyncEngine, text: str
) -> None:
    with pytest.raises(RefusedConfiguration, match="ADR-0027"):
        await load(PostgresConfiguration(clean_crawl), text)

    assert await _counts(clean_crawl) == _NOTHING


async def test_required_false_is_accepted_and_not_stored(clean_crawl: AsyncEngine) -> None:
    await load(PostgresConfiguration(clean_crawl), _VALID)

    for row in await _templates(clean_crawl):
        assert all("required" not in field for field in row["extraction"].values())


# ---------------------------------------------------------------------------
# A valid file
# ---------------------------------------------------------------------------


async def test_each_domain_is_written_active_with_its_settings(clean_crawl: AsyncEngine) -> None:
    await load(PostgresConfiguration(clean_crawl), _VALID)

    domains = await _domains(clean_crawl)
    assert set(domains) == {"shop.test:8099", "plain.test"}
    shop = domains["shop.test:8099"]
    assert shop["state"] == "active"
    assert shop["render_mode"] == "auto"
    assert shop["respect_robots"] is False
    # Both: the operator's floor, and the delay the next request waits.
    assert shop["configured_crawl_delay_ms"] == 5000
    assert shop["crawl_delay_ms"] == 5000
    plain = domains["plain.test"]
    assert plain["state"] == "active"
    assert plain["render_mode"] == "static"
    assert plain["respect_robots"] is True
    assert plain["crawl_delay_ms"] == plain["configured_crawl_delay_ms"] == 2500


async def test_each_template_is_active_version_one_and_the_worker_reads_back_the_same_rules(
    clean_crawl: AsyncEngine,
) -> None:
    await load(PostgresConfiguration(clean_crawl), _VALID)

    domains = await _domains(clean_crawl)
    # What the crawl path reads, through the codec it reads with.
    shop = await PostgresTemplates(clean_crawl).active_for(
        DomainId(domains["shop.test:8099"]["id"])
    )
    plain = await PostgresTemplates(clean_crawl).active_for(DomainId(domains["plain.test"]["id"]))

    by_pattern = {t.url_pattern: t for t in shop}
    assert set(by_pattern) == {"/p/.+", "/c/.+"}
    assert all(t.version == 1 and t.is_active for t in [*shop, *plain])
    assert by_pattern["/p/.+"].extraction == _SHOP_PRODUCT
    assert by_pattern["/p/.+"].page_kind is PageKind.PRODUCT
    assert by_pattern["/c/.+"].page_kind is PageKind.LISTING
    assert by_pattern["/c/.+"].extraction == {"title": FieldRule(selector="h1")}
    (plain_product,) = plain
    assert plain_product.extraction == {"title": FieldRule(selector=".name")}


async def test_a_run_covers_exactly_the_files_domains_with_one_queue_row_per_seed(
    clean_crawl: AsyncEngine,
) -> None:
    run_id = await load(PostgresConfiguration(clean_crawl), _VALID)

    domains = await _domains(clean_crawl)
    shop, plain = domains["shop.test:8099"]["id"], domains["plain.test"]["id"]
    async with clean_crawl.connect() as conn:
        (run_domains,) = (
            await conn.execute(
                sa.text("SELECT domain_ids FROM crawl.runs WHERE id = :r"), {"r": int(run_id)}
            )
        ).one()
        queue = (
            await conn.execute(
                sa.text("SELECT run_id, domain_id, url, depth FROM crawl.crawl_queue")
            )
        ).all()

    assert sorted(run_domains) == sorted([shop, plain])
    assert sorted((r.run_id, r.domain_id, r.url, r.depth) for r in queue) == sorted(
        [
            (int(run_id), shop, "http://shop.test:8099/p/one", 0),
            # A full URL on the domain is kept as given.
            (int(run_id), shop, "http://shop.test:8099/p/two", 0),
            # No scheme in the file: https.
            (int(run_id), plain, "https://plain.test/item/three", 0),
        ]
    )


# ---------------------------------------------------------------------------
# Loading again: versioned, never edited in place
# ---------------------------------------------------------------------------


async def test_a_domain_with_templates_but_no_seeds_is_still_in_the_run(
    clean_crawl: AsyncEngine,
) -> None:
    """The run's `domain_ids` is the selection the operator loaded. A domain
    left out because it had no seeds would be active but outside every run's
    selection, which is the one record of what the run was asked to cover."""
    text = """
domains:
  - host: seeded.test
    templates: []
    seeds: [/a]
  - host: unseeded.test
    templates:
      - name: p
        url_pattern: "/p/.+"
        extraction: { title: { selector: h1 } }
"""
    run = await load(PostgresConfiguration(clean_crawl), text)

    async with clean_crawl.connect() as conn:
        covered = (
            await conn.execute(
                sa.text("SELECT domain_ids FROM crawl.runs WHERE id = :r"), {"r": int(run)}
            )
        ).scalar_one()
    assert set(covered) == {int(d["id"]) for d in (await _domains(clean_crawl)).values()}


async def test_loading_twice_writes_version_two_and_keeps_version_one_inactive(
    clean_crawl: AsyncEngine,
) -> None:
    configuration = PostgresConfiguration(clean_crawl)
    await load(configuration, _VALID)
    first = {(r["domain_id"], r["url_pattern"]): r for r in await _templates(clean_crawl)}

    await load(configuration, _VALID)

    rows = await _templates(clean_crawl)
    assert len(rows) == 2 * len(first)
    for key, v1 in first.items():
        versions = {r["version"]: r for r in rows if (r["domain_id"], r["url_pattern"]) == key}
        assert set(versions) == {1, 2}
        # The very row the first load wrote, untouched apart from is_active.
        assert versions[1]["id"] == v1["id"]
        assert versions[1]["extraction"] == v1["extraction"]
        assert versions[1]["is_active"] is False
        assert versions[2]["is_active"] is True
        assert versions[2]["extraction"] == v1["extraction"]
    active = [(r["domain_id"], r["url_pattern"]) for r in rows if r["is_active"]]
    assert sorted(active) == sorted(first)


async def test_loading_twice_starts_a_new_run_and_updates_rather_than_duplicates_domains(
    clean_crawl: AsyncEngine,
) -> None:
    configuration = PostgresConfiguration(clean_crawl)
    first_run = await load(configuration, _VALID)
    before = await _domains(clean_crawl)

    changed = _VALID.replace("render_mode: auto", "render_mode: rendered").replace(
        "crawl_delay_ms: 5000", "crawl_delay_ms: 7000"
    )
    second_run = await load(configuration, changed)

    after = await _domains(clean_crawl)
    assert second_run != first_run
    assert set(after) == set(before)
    assert {h: r["id"] for h, r in after.items()} == {h: r["id"] for h, r in before.items()}
    shop = after["shop.test:8099"]
    assert shop["render_mode"] == "rendered"
    assert shop["crawl_delay_ms"] == shop["configured_crawl_delay_ms"] == 7000
    async with clean_crawl.connect() as conn:
        runs = (
            (await conn.execute(sa.text("SELECT id FROM crawl.runs ORDER BY id"))).scalars().all()
        )
        second_queue = (
            await conn.execute(
                sa.text("SELECT count(*) FROM crawl.crawl_queue WHERE run_id = :r"),
                {"r": int(second_run)},
            )
        ).scalar_one()
    assert runs == [int(first_run), int(second_run)]
    assert second_queue == 3


@pytest.mark.parametrize("state", ["paused", "broken", "archived"])
async def test_loading_refuses_to_move_a_domain_only_a_human_may_move(
    clean_crawl: AsyncEngine, state: str
) -> None:
    """Review finding 1. Reloading a file to fix a selector reset a domain
    that three 403s had paused, which is a retry through a block (AGENTS.md
    rule 8, ADR-0004). Resume, re-review and un-archive are an operator's
    decisions about that one domain (spec 001 §2), so the load is refused and
    nothing is written."""
    configuration = PostgresConfiguration(clean_crawl)
    await load(configuration, _VALID)
    async with clean_crawl.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE crawl.domains SET state = CAST(:s AS crawl.domain_state) "
                "WHERE host = 'shop.test:8099'"
            ),
            {"s": state},
        )
    before = await _counts(clean_crawl)

    with pytest.raises(RefusedConfiguration, match=state):
        await load(configuration, _VALID)

    assert await _counts(clean_crawl) == before
    assert (await _domains(clean_crawl))["shop.test:8099"]["state"] == state


@pytest.mark.parametrize("state", ["discovered", "awaiting_approval"])
async def test_loading_approves_a_candidate_domain(clean_crawl: AsyncEngine, state: str) -> None:
    """The file is the operator's approval, so a candidate domain walks the
    lifecycle's own edges to `active`."""
    configuration = PostgresConfiguration(clean_crawl)
    await load(configuration, _VALID)
    async with clean_crawl.begin() as conn:
        await conn.execute(
            sa.text("UPDATE crawl.domains SET state = CAST(:s AS crawl.domain_state)"),
            {"s": state},
        )

    await load(configuration, _VALID)

    assert {r["state"] for r in (await _domains(clean_crawl)).values()} == {"active"}


async def test_reloading_keeps_a_backoff_in_progress(clean_crawl: AsyncEngine) -> None:
    """A 429 doubled the delay. Reloading the file sets the operator's floor
    but must not wipe the backoff the site asked for: the live delay only
    rises to meet a higher floor (spec 002 §4)."""
    configuration = PostgresConfiguration(clean_crawl)
    await load(configuration, _VALID)
    async with clean_crawl.begin() as conn:
        await conn.execute(sa.text("UPDATE crawl.domains SET crawl_delay_ms = 600000"))

    await load(configuration, _VALID)

    for row in (await _domains(clean_crawl)).values():
        assert row["crawl_delay_ms"] == 600000
        assert row["configured_crawl_delay_ms"] < 600000


# ---------------------------------------------------------------------------
# Atomicity: a file that fails part-way writes nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "broken",
    [
        _VALID.replace(
            'title: { selector: ".name" }', 'title: { selector: ".name", transform: [titlecase] }'
        ),
        _VALID.replace('title: { selector: ".name" }', "title: { attr: text }"),
    ],
    ids=["unknown-transform", "missing-selector"],
)
async def test_an_invalid_template_in_the_second_domain_writes_nothing(
    clean_crawl: AsyncEngine, broken: str
) -> None:
    with pytest.raises((ValueError, KeyError)):
        await load(PostgresConfiguration(clean_crawl), broken)

    assert await _counts(clean_crawl) == _NOTHING


async def test_a_database_refusal_on_the_second_domain_rolls_back_the_first(
    clean_crawl: AsyncEngine,
) -> None:
    """The cases above fail while parsing, before any write. This one parses
    and is refused by Postgres itself (`configured_crawl_delay_ms_non_negative`)
    after the first domain and its templates have been written inside the
    transaction, which is the case the single transaction exists for."""
    broken = _VALID.replace("crawl_delay_ms: 2500", "crawl_delay_ms: -1")

    with pytest.raises(sa.exc.DBAPIError):
        await load(PostgresConfiguration(clean_crawl), broken)

    assert await _counts(clean_crawl) == _NOTHING


async def test_a_failed_reload_leaves_the_previous_load_exactly_as_it_was(
    clean_crawl: AsyncEngine,
) -> None:
    """Rule 12's other half: a reload that fails must not have deactivated
    version 1 on the way to failing."""
    configuration = PostgresConfiguration(clean_crawl)
    await load(configuration, _VALID)
    before = (
        await _counts(clean_crawl),
        await _templates(clean_crawl),
        await _domains(clean_crawl),
    )

    with pytest.raises(sa.exc.DBAPIError):
        await load(
            configuration,
            _VALID.replace("crawl_delay_ms: 5000", "crawl_delay_ms: 9000").replace(
                "crawl_delay_ms: 2500", "crawl_delay_ms: -1"
            ),
        )

    after = (await _counts(clean_crawl), await _templates(clean_crawl), await _domains(clean_crawl))
    assert after == before


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------


def _cli(database_url: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "spydra.load", str(path)],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


async def test_the_cli_refuses_required_true_non_zero_naming_adr_0027(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    path = tmp_path / "refused.yaml"
    path.write_text(
        _VALID.replace(
            'title: { selector: ".name" }', 'title: { selector: ".name", required: true }'
        )
    )

    done = _cli(database_url, path)

    assert done.returncode != 0
    assert "refused:" in done.stderr
    assert "ADR-0027" in done.stderr
    assert await _counts(clean_crawl) == _NOTHING


async def test_the_cli_loads_a_valid_file_and_reports_the_run(
    clean_crawl: AsyncEngine, database_url: str, tmp_path: Path
) -> None:
    path = tmp_path / "valid.yaml"
    path.write_text(_VALID)

    done = _cli(database_url, path)

    assert done.returncode == 0, done.stderr
    async with clean_crawl.connect() as conn:
        (run_id,) = (await conn.execute(sa.text("SELECT id FROM crawl.runs"))).scalars().all()
    assert f"run {run_id} started" in done.stdout


async def test_a_template_max_depth_is_refused_and_nothing_is_written(
    clean_crawl: AsyncEngine,
) -> None:
    """2.3 review, finding 10: `max_depth` is the domain's (spec 001 §1)."""
    text = _VALID.replace(
        "        page_kind: listing\n",
        "        page_kind: listing\n        discovery: { max_depth: 2 }\n",
    )
    assert "max_depth" in text

    with pytest.raises(RefusedConfiguration, match="max_depth"):
        await load(PostgresConfiguration(clean_crawl), text)

    assert await _counts(clean_crawl) == _NOTHING
