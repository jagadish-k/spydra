"""Spec 002 §7's backpressure: page claiming slows when assets pile up.

> If `asset_queue` pending count exceeds **10,000**, page workers sleep
> 500 ms between claims until it drops below **8,000**. Without this a fast
> crawl over an image-heavy catalogue builds a queue that outlives the run by
> hours.

**Two numbers, so this object holds state, and that is the design.** A
stateless `pending > 10_000` would release at 10,001 — one row — and a queue
hovering there would flap between slowed and unslowed on every claim. The gap
between 10,000 and 8,000 is a Schmitt trigger: it engages high, releases low,
and the only way to implement it is to remember which side you are on.

**It slows claiming; it never stops it.** A worker that stopped claiming
while the queue drained would be a worker that cannot be told to stop, and
nothing drains `asset_queue` at all until `5.2` — so a hard stop here would
deadlock every phase-1 crawl of an image-heavy site rather than slow it.

`5.5` re-tunes the numbers against real volume, once something drains the
queue. They are deliberately named rather than inlined so that re-tune is a
diff of two constants.
"""

import asyncio
from typing import Final

# Spec 002 §7, verbatim.
ENGAGE_ABOVE: Final[int] = 10_000
RELEASE_BELOW: Final[int] = 8_000
SLEEP_MS: Final[int] = 500


class AssetPressure:
    """The hysteresis band. One per worker process.

    In-process, like ADR-0003's asset concurrency and for the same reason:
    this is a throughput knob, not a correctness property. Two worker
    replicas each slowing independently is the right behaviour anyway — they
    are both reading the same queue depth.
    """

    def __init__(
        self,
        *,
        engage_above: int = ENGAGE_ABOVE,
        release_below: int = RELEASE_BELOW,
        sleep_ms: int = SLEEP_MS,
    ) -> None:
        if release_below > engage_above:
            # A band that releases above where it engages is a toggle that
            # can never turn off. Refused at construction rather than
            # debugged at 3am from a worker that will not claim.
            raise ValueError(
                f"release_below ({release_below}) must not exceed "
                f"engage_above ({engage_above}): the band would never release"
            )
        self._engage_above = engage_above
        self._release_below = release_below
        self._sleep_s = sleep_ms / 1000
        self._engaged = False

    @property
    def engaged(self) -> bool:
        """Whether claiming is currently being slowed.

        Exposed for `2.8`'s progress event: spec 002 §7 says the depth
        "belongs on screen rather than in a log", and whether the brake is on
        is the half of that a human acts on.
        """
        return self._engaged

    def update(self, pending: int) -> bool:
        """Feed the current depth in; get back whether the brake is on.

        Separate from `before_claim` so the decision is testable without
        waiting half a second per case — the band's whole behaviour is in
        this function, and a test of it should not cost wall-clock time.
        """
        if self._engaged:
            # Release only below the LOW number. Releasing at `engage_above`
            # is the flap the two numbers exist to prevent.
            if pending < self._release_below:
                self._engaged = False
        elif pending > self._engage_above:
            self._engaged = True
        return self._engaged

    async def before_claim(self, pending: int) -> bool:
        """Update the band and sleep if it is engaged. Returns `engaged`.

        Called by `1.13`'s claim loop before each claim, which is what spec
        002 §7's "sleep 500 ms between claims" means. `asyncio.sleep`, so the
        asset and rendered pools in the same process keep running — a
        `time.sleep` here would stop all three (ADR-0003: one process, three
        loops).
        """
        if self.update(pending):
            await asyncio.sleep(self._sleep_s)
        return self._engaged
