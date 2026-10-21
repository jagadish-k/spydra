"""Spec 002 §7's backpressure band (BUILD_PLAN 1.12).

The two numbers — engage above 10,000, release below 8,000 — are a Schmitt
trigger, and the only test that can tell a band from a plain threshold is one
that asks what happens at 9,000 **from each side**. Everything else here
passes against `pending > 10_000`.

The sleep itself is asserted on observed timestamps (TESTING.md §2's rule for
politeness, and the same reasoning: a mocked clock proves the test's
arithmetic, not the system's behaviour).
"""

import asyncio
import time

import pytest

from spydra.scheduler.asset_pressure import (
    ENGAGE_ABOVE,
    RELEASE_BELOW,
    SLEEP_MS,
    AssetPressure,
)


def test_the_numbers_are_spec_002_7s() -> None:
    """Named rather than inlined so `5.5`'s re-tune is a two-line diff — and
    asserted here so the re-tune cannot happen by accident."""
    assert (ENGAGE_ABOVE, RELEASE_BELOW, SLEEP_MS) == (10_000, 8_000, 500)


def test_a_quiet_queue_does_not_slow_claiming() -> None:
    assert AssetPressure().update(0) is False
    assert AssetPressure().update(9_999) is False


def test_the_brake_engages_above_ten_thousand_and_not_at_it() -> None:
    """Spec 002 §7 says "exceeds 10,000"."""
    assert AssetPressure().update(10_001) is True
    assert AssetPressure().update(10_000) is False


def test_nine_thousand_means_two_different_things() -> None:
    """The band, and the only test that distinguishes it from a threshold.

    Engaged at 9,000 the brake stays on, because release is below 8,000.
    Not engaged at 9,000 it stays off, because engage is above 10,000. A
    stateless `pending > 10_000` gets the first of those wrong and lets a
    queue hovering at the threshold flap on every claim — which is the
    behaviour two numbers exist to prevent.
    """
    engaged = AssetPressure()
    engaged.update(10_001)
    assert engaged.update(9_000) is True

    idle = AssetPressure()
    assert idle.update(9_000) is False


def test_the_brake_releases_below_eight_thousand_and_not_at_it() -> None:
    pressure = AssetPressure()
    pressure.update(10_001)

    assert pressure.update(8_000) is True
    assert pressure.update(7_999) is False
    # And having released, it does not re-engage until it is high again.
    assert pressure.update(9_000) is False


def test_a_band_that_could_never_release_is_refused() -> None:
    """A `release_below` above `engage_above` is a brake with no off switch.
    Refused at construction rather than debugged from a worker that will not
    claim."""
    with pytest.raises(ValueError, match="never release"):
        AssetPressure(engage_above=8_000, release_below=10_000)

    # The degenerate-but-usable case is allowed: equal numbers are a plain
    # threshold, which is what `5.5` might choose.
    assert AssetPressure(engage_above=1, release_below=1).update(2) is True


async def test_an_engaged_brake_measurably_slows_claiming() -> None:
    """Observed timestamps, not a mocked clock.

    Three claims with the brake on must cost three sleeps. The pair below —
    the same three with the brake off — is what makes this a measurement of
    the brake rather than of the test runner.
    """
    pressure = AssetPressure(sleep_ms=100)

    started = time.monotonic()
    for _ in range(3):
        await pressure.before_claim(10_001)
    slowed = time.monotonic() - started

    assert slowed >= 0.3, f"three 100 ms sleeps took {slowed:.3f}s"


async def test_an_idle_brake_costs_nothing() -> None:
    pressure = AssetPressure(sleep_ms=100)

    started = time.monotonic()
    for _ in range(3):
        await pressure.before_claim(10)
    elapsed = time.monotonic() - started

    assert elapsed < 0.1, f"an idle brake cost {elapsed:.3f}s"


async def test_the_other_pools_keep_running_while_the_brake_is_on() -> None:
    """ADR-0003 puts three loops in one process, so this has to be
    `asyncio.sleep`.

    A `time.sleep` would stop the asset and rendered pools as well — the
    page path slowing down would silently stop the thing that drains the
    queue, which is the deadlock this backpressure is supposed to avoid. The
    counter is the evidence: it cannot advance if the loop is blocked.
    """
    ticks = 0

    async def other_pool() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    companion = asyncio.create_task(other_pool())
    try:
        await AssetPressure(sleep_ms=200).before_claim(10_001)
    finally:
        companion.cancel()

    assert ticks >= 5, f"the companion loop only ran {ticks} times"
