"""The Clock port (ADR-0008).

Exists so time-dependent scheduler logic — jitter, backoff decay, lease
expiry arithmetic — can be unit-tested without sleeping.

**It is not a licence to simulate politeness.** TESTING.md §2 requires the
politeness tests to assert on observed fetch timestamps from two real workers
against a real database. A test that substitutes a Clock and asserts the gate
*would have* waited passes while the crawler is rude to a real supplier. Use
this port for logic; prove the guarantee with elapsed time.
"""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Wall-clock time, timezone-aware and in UTC.

        Everything persisted is TIMESTAMPTZ (spec 001 §1), so a naive
        datetime here is a bug that surfaces as an hour of silent drift.
        """
        ...

    def monotonic(self) -> float:
        """Seconds from an arbitrary origin, for measuring gaps.

        Separate from `now()` because wall-clock time can step backwards and
        the asset gate's inter-request gap must not (spec 002 §6).
        """
        ...

    async def sleep(self, seconds: float) -> None: ...
