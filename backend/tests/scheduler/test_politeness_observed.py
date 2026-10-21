"""Politeness proven on observed time (BUILD_PLAN 1.9, TESTING.md §2).

**TESTING.md §2 is explicit that the gate's own arithmetic is not enough.**
`ports/clock.py` says it in terms: "A test that substitutes a Clock and
asserts the gate *would have* waited passes while the crawler is rude to a
real supplier. Use this port for logic; prove the guarantee with elapsed
time."

So this file uses the **real** clock and the **real** RNG, waits the gaps the
gate asks for, and asserts on the intervals a supplier would actually see.
That is why the delays here are milliseconds rather than the configured
seconds: the property under test is the *shape* of the gaps, and a suite that
took two seconds per request would be a suite nobody runs.

The sibling `test_politeness.py` seeds the RNG and asserts exact values.
Neither file is sufficient alone — one proves the arithmetic, this one proves
the gate is actually wired to the passage of time.
"""

import asyncio
import time
from datetime import UTC, datetime
from itertools import pairwise

from spydra.scheduler.politeness import DomainPoliteness, PolitenessGate


class RealClock:
    """The real thing. No injection, no seam — that is the point of this file."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


async def observe_gaps(delay_ms: int, requests: int) -> list[float]:
    """Drive the gate like a worker would and record the real gaps.

    Deliberately shaped like `1.13`'s loop will be: ask the gate when the
    domain is next eligible, wait until then, "fetch", repeat. A gate that
    returned a time nobody waited for would make this list uniform.
    """
    gate = PolitenessGate(clock=RealClock())
    stamps: list[float] = []

    for _ in range(requests):
        stamps.append(time.monotonic())
        # The delay is rebuilt each round rather than carried through
        # `decision.state`, so the decay does not shrink it and the only
        # thing varying between gaps is the jitter. Carrying it would make a
        # falling sequence of gaps look like variation.
        decision = gate.on_success(DomainPoliteness(crawl_delay_ms=delay_ms, floor_ms=delay_ms))
        wait = (decision.next_eligible_at - datetime.now(UTC)).total_seconds()
        if wait > 0:
            await asyncio.sleep(wait)

    return [b - a for a, b in pairwise(stamps)]


async def test_observed_inter_request_gaps_show_jitter_not_a_constant() -> None:
    """Spec 002 §9's acceptance line, and TESTING.md §2's.

    The failure this catches is a gate that computes jitter and then returns
    a time the worker does not actually wait for, or a gate whose jitter is
    effectively constant. Both pass every unit test in the sibling file and
    both give a supplier a metronome — which spec 002 §2 calls a bot
    signature, and which is the signature that gets a crawler blocked.
    """
    gaps = await observe_gaps(delay_ms=60, requests=12)

    assert len(gaps) == 11
    # Each gap is at least 0.7x the delay: the floor of the jitter range,
    # allowing for the scheduler being a little late but never early.
    assert min(gaps) >= 0.06 * 0.7, f"a gap was shorter than the jitter floor: {min(gaps)}"

    # And they are not all the same. Rounded to milliseconds so this is about
    # the jitter rather than about scheduler noise — at 60 ms a ±30% jitter
    # spans 42–78 ms, so distinct values are unmissable while noise is not.
    distinct = {round(g, 3) for g in gaps}
    assert len(distinct) >= 6, (
        f"only {len(distinct)} distinct gaps in {len(gaps)} requests — the gaps a "
        f"supplier sees are effectively constant, which is the bot signature "
        f"spec 002 §2 forbids. Gaps: {[round(g, 3) for g in gaps]}"
    )

    spread = max(gaps) - min(gaps)
    assert spread > 0.006, f"the gaps span only {spread:.4f}s, which is not ±30%"


async def test_the_gate_asks_for_a_future_time_so_the_worker_actually_waits() -> None:
    """The wiring, separately from the shape. If `next_eligible_at` were in
    the past the loop above would never sleep and the gaps would collapse to
    nothing — and the gaps test would then fail for a reason that reads like
    a jitter problem."""
    gate = PolitenessGate(clock=RealClock())
    before = datetime.now(UTC)
    decision = gate.on_success(DomainPoliteness(crawl_delay_ms=2000, floor_ms=2000))

    waited = (decision.next_eligible_at - before).total_seconds()
    assert 2.0 * 0.7 <= waited <= 2.0 * 1.3 + 0.1, f"asked to wait {waited}s for a 2s delay"
