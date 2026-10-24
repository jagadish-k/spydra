"""`python -m spydra.runctl <pause|resume|stop> <run_id>` (BUILD_PLAN 2.7,
ADR-0041) — the operator's terminal entry point, as an operator drives it.

What `make pause-run|resume-run|stop-run` runs in the api container is
exactly this module; the unit path here is the module itself against the
real adapter and the real database, as a subprocess, so what is asserted
is what the operator sees: stdout and the exit code. On a fenced miss the
CLI must print the run's actual state and exit 1 — an operator tool that
prints success over a refusal is worse than no tool, because it is
believed.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from spydra.adapters.postgres.runs import PostgresRuns
from spydra.domain.ids import RunId
from tests.adapters.postgres.seed import seed_domain, seed_queue_row, seed_run

pytestmark = pytest.mark.integration

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def runctl(verb: str, run_id: int) -> subprocess.CompletedProcess[str]:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    return subprocess.run(
        [sys.executable, "-m", "spydra.runctl", verb, str(run_id)],
        cwd=BACKEND_ROOT,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        timeout=60,
    )


async def a_running_run_with_pending_rows(
    engine: AsyncEngine, *, pending: int = 2
) -> tuple[RunId, int]:
    domain = await seed_domain(engine)
    run = await seed_run(engine, [int(domain)])
    for n in range(pending):
        await seed_queue_row(engine, run, domain, f"https://v.test/{n}")
    return run, pending


async def test_pause_prints_the_transition_and_exits_0(clean_crawl: AsyncEngine) -> None:
    run, _ = await a_running_run_with_pending_rows(clean_crawl)

    done = runctl("pause", run)

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"run {run} paused" in done.stdout


async def test_stop_names_the_abandoned_count_and_exits_0(clean_crawl: AsyncEngine) -> None:
    """Stop's output is the report of the work not done: the abandoned
    count, plus the stats line carrying `pages_abandoned`."""
    run, pending = await a_running_run_with_pending_rows(clean_crawl)

    done = runctl("stop", run)

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"run {run} stopped; {pending} pages abandoned" in done.stdout
    assert "stats" in done.stdout
    assert f'"pages_abandoned": {pending}' in done.stdout
    async with clean_crawl.connect() as conn:
        row = (
            await conn.execute(
                sa.text("SELECT state::text AS s, stop_reason FROM crawl.runs WHERE id = :r"),
                {"r": run},
            )
        ).one()
    assert (row.s, row.stop_reason) == ("stopped", "stopped by operator")


async def test_resume_prints_the_transition_and_exits_0(clean_crawl: AsyncEngine) -> None:
    run, _ = await a_running_run_with_pending_rows(clean_crawl)
    assert (await PostgresRuns(clean_crawl).pause_run(RunId(run))).transitioned

    done = runctl("resume", run)

    assert done.returncode == 0, done.stdout + done.stderr
    assert f"run {run} resumed" in done.stdout


@pytest.mark.parametrize(
    ("verb", "state"),
    [
        ("pause", "stopped"),
        ("pause", "completed"),
        ("resume", "running"),
        ("resume", "stopped"),
        ("stop", "completed"),
        ("stop", "failed"),
    ],
    ids=lambda value: str(value),
)
async def test_a_miss_refuses_names_the_actual_state_and_exits_1(
    clean_crawl: AsyncEngine, verb: str, state: str
) -> None:
    """The CLI never lies. Every wrong-state call prints `state is <the
    run's actual state>` — not the state the operator asked for — and exits
    nonzero, because a guarded UPDATE that matched nothing is a refusal."""
    domain = await seed_domain(clean_crawl)
    run = await seed_run(clean_crawl, [int(domain)])
    reason = None if state in ("running", "completed") else "fixture"
    async with clean_crawl.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE crawl.runs SET state = CAST(:s AS crawl.run_state), "
                "stop_reason = :r WHERE id = :i"
            ),
            {"s": state, "r": reason, "i": int(run)},
        )

    refused = runctl(verb, int(run))

    assert refused.returncode == 1, refused.stdout + refused.stderr
    past = {"pause": "paused", "resume": "resumed", "stop": "stopped"}[verb]
    assert f"run {int(run)} not {past}: state is {state}" in refused.stdout


def test_an_unknown_run_refuses_and_exits_1(clean_crawl: AsyncEngine) -> None:
    refused = runctl("stop", 987_654_321)
    assert refused.returncode == 1, refused.stdout + refused.stderr
    assert "no such run" in refused.stdout


def test_a_bad_verb_or_argument_prints_usage_and_exits_nonzero() -> None:
    """The same guard `make load` has: a target that accepts anything and
    fails mysteriously is worse than one that refuses up front."""
    for argv in (["frobnicate", "1"], ["pause"], ["pause", "not-a-number"], ["pause", "1", "2"]):
        bad = subprocess.run(
            [sys.executable, "-m", "spydra.runctl", *argv],
            cwd=BACKEND_ROOT,
            env={**os.environ, "DATABASE_URL": os.environ.get("DATABASE_URL", "unused")},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert bad.returncode != 0, argv
        assert "usage: python -m spydra.runctl" in bad.stderr, argv
