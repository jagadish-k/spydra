"""`python -m spydra.runctl <pause|resume|stop> <run_id>`: drive a run's
lifecycle from the operator's terminal (BUILD_PLAN 2.7, ADR-0041).

An operator entry point ships NOW rather than in 3.4 (the user decision in
the task file): the adapter plus a make target today, and 3.4's API wraps
the same `PostgresRuns` calls. Same shape as `spydra.load` — adapter
directly, no port — because the worker is not a caller and the Frontier
port stays the crawler's.

On a fenced miss the CLI prints the run's actual state and exits nonzero:
an operator tool must never print a lie, and a guarded UPDATE that matched
nothing is a refusal, not a success. For stop it prints the stats —
`pages_abandoned` is the run's report of the work it did not do.

Pause freezes dequeue, not discovery: in-flight rows finish and their links
still enqueue. Stop is terminal: pending rows are abandoned, in-flight rows
finish their fetch and close `done`, and the run can never be resurrected.
"""

import asyncio
import json
import os
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from spydra.adapters.postgres.runs import PostgresRuns
from spydra.domain.ids import RunId

__all__ = ["main"]

_VERBS = ("pause", "resume", "stop")


async def main(verb: str, run_id: RunId) -> int:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        runs = PostgresRuns(engine)
        if verb == "pause":
            outcome = await runs.pause_run(run_id)
            if not outcome.transitioned:
                return _refused(run_id, "paused", outcome.state)
            print(f"run {int(run_id)} paused")
            return 0
        if verb == "resume":
            outcome = await runs.resume_run(run_id)
            if not outcome.transitioned:
                return _refused(run_id, "resumed", outcome.state)
            if outcome.stats is not None:
                # The queue drained while paused; resume completed the run.
                print(f"run {int(run_id)} resumed; drained, completed")
                print(f"stats {json.dumps(outcome.stats, sort_keys=True)}")
            else:
                print(f"run {int(run_id)} resumed")
            return 0
        outcome = await runs.stop_run(run_id)
        if not outcome.transitioned:
            return _refused(run_id, "stopped", outcome.state)
        print(f"run {int(run_id)} stopped; {outcome.abandoned} pages abandoned")
        print(f"stats {json.dumps(outcome.stats, sort_keys=True)}")
        return 0
    finally:
        await engine.dispose()


def _refused(run_id: RunId, verb: str, state: str | None) -> int:
    if state is None:
        print(f"run {int(run_id)} not {verb}: no such run")
    else:
        print(f"run {int(run_id)} not {verb}: state is {state}")
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in _VERBS:
        sys.exit("usage: python -m spydra.runctl <pause|resume|stop> <run_id>")
    try:
        run_id = RunId(int(sys.argv[2]))
    except ValueError:
        sys.exit("usage: python -m spydra.runctl <pause|resume|stop> <run_id>")
    sys.exit(asyncio.run(main(sys.argv[1], run_id)))
