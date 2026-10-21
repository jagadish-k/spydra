"""The politeness gate's arithmetic (BUILD_PLAN 1.9, spec 002 §2/§4).

Written from spec 002 §4's table and ADR-0004, not from the gate. The
observed-timing half is in `test_politeness_observed.py` — TESTING.md §2
requires the gaps themselves to be proven against real elapsed time, and a
seeded RNG proves arithmetic rather than politeness.

**The assertions that matter most are the ones about what does NOT happen.**
A 403 must not back off (that is a slower retry, which is still a retry);
one 403 and two 429s must not pause a domain; a 500 must not be charged to
the domain at all.
"""

import random
from datetime import UTC, datetime, timedelta

import pytest

from spydra.scheduler.politeness import (
    BACKOFF_CAP_MS,
    BLOCK_THRESHOLD,
    JITTER_MAX,
    JITTER_MIN,
    DomainPoliteness,
    PolitenessGate,
)

FIXED_NOW = datetime(2026, 10, 21, 14, 0, tzinfo=UTC)


class FakeClock:
    def now(self) -> datetime:
        return FIXED_NOW

    def monotonic(self) -> float:
        return 0.0

    async def sleep(self, seconds: float) -> None:  # pragma: no cover
        raise AssertionError("the gate must not sleep; it returns a time")


def gate(seed: int = 7) -> PolitenessGate:
    """A gate whose jitter is reproducible.

    Seeded so the arithmetic can be asserted exactly. `ports/clock.py` warns
    that the Clock port "is not a licence to simulate politeness", and the
    same applies here: the guarantee is proven in the observed-timing file.
    """
    return PolitenessGate(clock=FakeClock(), rng=random.Random(seed))


def state(
    crawl_delay_ms: int = 2000,
    consecutive_failures: int = 0,
    consecutive_403s: int = 0,
) -> DomainPoliteness:
    """Spelled out rather than `**kwargs`, so mypy checks every call site
    here against the dataclass."""
    return DomainPoliteness(
        crawl_delay_ms=crawl_delay_ms,
        consecutive_failures=consecutive_failures,
        consecutive_403s=consecutive_403s,
    )


# ---------------------------------------------------------------------------
# F8, F16 — backoff, and what is NOT charged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("start,expected", [(2000, 4000), (8000, 16_000), (500_000, 900_000)])
async def test_rate_limiting_doubles_the_delay_capped_at_fifteen_minutes(
    start: int, expected: int
) -> None:
    """ADR-0004: ×2, capped at 15 minutes. The cap case is the third
    parameter — uncapped, 500 s would double to 1,000 s and a domain that
    rate-limits repeatedly would walk its delay toward hours and never
    finish a run."""
    decision = gate().on_rate_limited(state(crawl_delay_ms=start))
    assert decision.crawl_delay_ms == expected
    assert decision.crawl_delay_ms <= BACKOFF_CAP_MS
    assert decision.consecutive_failures == 1
    assert decision.pause_domain is False, "429 and 503 leave the domain active"


async def test_a_server_error_is_not_charged_to_the_domain() -> None:
    """Spec 002 §4's last row: "5xx (other) — retry up to 3 attempts, then
    `failed`. **No domain-level penalty.**" A 500 is the site being broken,
    not the site refusing us; charging it toward a pause would stop crawling
    a domain that is merely having a bad day. The row is retired by the
    frontier's own attempt count."""
    before = state(crawl_delay_ms=2000, consecutive_failures=1, consecutive_403s=1)
    decision = gate().on_server_error(before)

    assert decision.crawl_delay_ms == 2000, "a 500 must not back the domain off"
    assert decision.consecutive_failures == 1, "unchanged, not incremented"
    assert decision.consecutive_403s == 1, "and not reset either — nothing happened"
    assert decision.pause_domain is False


# ---------------------------------------------------------------------------
# F9, F10, F11, F12 — the block, which is what ADR-0004 is for
# ---------------------------------------------------------------------------


async def test_a_403_counts_but_does_not_back_off() -> None:
    """ADR-0004: "Never retry through a 403." Backing off is a *slower*
    retry, which is still a retry — and a site that has decided to refuse us
    reads continued requests as confirmation that we are a bot, which is how
    a temporary block becomes permanent."""
    decision = gate().on_forbidden(state(crawl_delay_ms=2000))

    assert decision.crawl_delay_ms == 2000, "a 403 must not double the delay"
    assert decision.consecutive_403s == 1
    assert decision.pause_domain is False


async def test_the_third_consecutive_403_pauses_the_domain_and_abandons_its_work() -> None:
    """ADR-0004 and spec 002 §9. The **third**, not the second or the fourth.

    `abandon_queue` travels with the pause because the ADR requires the work
    not done to be recorded rather than deleted: "the abandoned rows stay in
    the queue marked `abandoned` so the run report can show the work that was
    not done, rather than reporting a clean finish"."""
    g = gate()
    current = state(crawl_delay_ms=2000)

    first = g.on_forbidden(current)
    assert first.pause_domain is False
    second = g.on_forbidden(first.state)
    assert second.pause_domain is False, "two 403s is not three"

    third = g.on_forbidden(second.state)
    assert third.consecutive_403s == BLOCK_THRESHOLD
    assert third.pause_domain is True
    assert third.abandon_queue is True, "the work not done must be recorded, not dropped"


async def test_a_success_between_403s_resets_the_count() -> None:
    """What "consecutive" means, and the half that is easy to omit. Without
    this reset, a domain that returns the odd 403 over a long crawl — a WAF
    hiccup, a bad edge node — accumulates three eventually and pauses, which
    ADR-0004's Consequences accepts as a cost for *consecutive* failures and
    not for scattered ones."""
    g = gate()
    after_first = g.on_forbidden(state())
    after_success = g.on_success(after_first.state)
    assert after_success.consecutive_403s == 0
    assert after_success.consecutive_failures == 0

    second = g.on_forbidden(after_success.state)
    third = g.on_forbidden(second.state)
    assert third.pause_domain is False, "403, 200, 403, 403 is not three consecutive"


async def test_one_403_and_two_429s_does_not_pause_the_domain() -> None:
    """The reason the gate tracks 403s separately.

    Spec 002 §4 increments `consecutive_failures` for 403, 429 **and** 503,
    while ADR-0004 pauses on three consecutive **403s**. Both cannot be read
    off one counter — and the single-counter implementation is the obvious
    one, so this test exists to make it fail. It would pause a domain that
    refused us once and was busy twice: a pause the operator did not earn,
    needing manual resumption, on a site that never blocked us."""
    g = gate()
    after_403 = g.on_forbidden(state())
    after_429 = g.on_rate_limited(after_403.state)
    final = g.on_rate_limited(after_429.state)

    assert final.consecutive_failures == 3, "spec 002 §4 counts all three"
    assert final.consecutive_403s == 1, "but only one of them was a refusal"
    assert final.pause_domain is False


async def test_two_429s_followed_by_one_403_does_not_pause_the_domain() -> None:
    """The ordering the sibling test above does not reach, and the one the
    single-counter bug actually fires on.

    `on_forbidden` must count **403s**, not failures. Reading it off
    `consecutive_failures` passes every other test in this file — including
    "one 403 and two 429s" — because there the 403 comes first and the
    counters happen to agree. Put the 403 **last** and they diverge: the
    shared counter is already at 2, so the first refusal the site ever sends
    reads as the third and pauses the domain on the spot.

    That is the worst version of the bug ADR-0004's cost paragraph accepts.
    It accepts that "a transient 403 — a WAF hiccup, a bad edge node — pauses
    a domain that would have recovered", on the basis that three consecutive
    refusals are strong evidence. One refusal after two busy responses is not
    evidence of anything, and the operator still has to resume it by hand.

    Found by mutation: this was the one guard the first matrix did not cover.
    """
    g = gate()
    after_first_429 = g.on_rate_limited(state())
    after_second_429 = g.on_rate_limited(after_first_429.state)
    assert after_second_429.consecutive_failures == 2
    assert after_second_429.consecutive_403s == 0

    first_refusal = g.on_forbidden(after_second_429.state)

    assert first_refusal.consecutive_403s == 1, "one refusal is one refusal"
    assert first_refusal.consecutive_failures == 3, "spec 002 §4 still counts all three"
    assert first_refusal.pause_domain is False, (
        "a single 403 after two 429s paused the domain — the pause is being read "
        "off consecutive_failures rather than off consecutive 403s (ADR-0004)"
    )
    assert first_refusal.abandon_queue is False


async def test_rate_limiting_does_not_reset_the_403_count() -> None:
    """A site that rate-limits between refusals has not stopped refusing.
    Resetting here would let 403, 429, 403, 429, 403 run for ever."""
    g = gate()
    after_403 = g.on_forbidden(state())
    after_429 = g.on_rate_limited(after_403.state)
    assert after_429.consecutive_403s == 1


# ---------------------------------------------------------------------------
# F13 — the decay
# ---------------------------------------------------------------------------


async def test_a_success_decays_the_delay_but_never_below_the_floor() -> None:
    """Spec 002 §4: 10% per success, never below the configured value."""
    g = gate()
    decision = g.on_success(state(crawl_delay_ms=10_000))
    assert decision.crawl_delay_ms == 9000
    assert decision.consecutive_failures == 0

    at_floor = g.on_success(state(crawl_delay_ms=2000))
    assert at_floor.crawl_delay_ms == 2000, "the floor is a floor"

    below = g.on_success(DomainPoliteness(crawl_delay_ms=2100, floor_ms=2000))
    assert below.crawl_delay_ms == 2000, "decay must clamp, not undershoot"


async def test_backing_off_and_decaying_are_not_symmetrical() -> None:
    """Deliberate, and worth asserting so nobody "fixes" it. ×2 up and ×0.9
    down means a domain that rate-limits once takes several successes to come
    back — which is the polite direction. A symmetrical recovery would return
    to full speed immediately after the one response that said slow down."""
    g = gate()
    backed_off = g.on_rate_limited(state(crawl_delay_ms=2000))
    assert backed_off.crawl_delay_ms == 4000

    recovered = g.on_success(backed_off.state)
    assert recovered.crawl_delay_ms == 3600, "one success does not undo one backoff"
    assert recovered.crawl_delay_ms > 2000


# ---------------------------------------------------------------------------
# F1, F2 — the robots floor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("configured_ms", "robots_s", "expected_ms", "why"),
    [
        (2000, 10.0, 10_000, "Crawl-delay: 10 raises a 2s delay"),
        (30_000, 1.0, 30_000, "Crawl-delay: 1 must NOT lower a 30s delay"),
        (2000, 1.0, 2000, "Crawl-delay: 1 must NOT lower a 2s delay"),
        (2000, None, 2000, "no Crawl-delay leaves the configured value alone"),
        (2000, 2.0, 2000, "an equal delay changes nothing"),
    ],
)
async def test_crawl_delay_is_a_floor_and_never_a_ceiling(
    configured_ms: int, robots_s: float | None, expected_ms: int, why: str
) -> None:
    """Spec 002 §5, and the fixture from `1.4` says the same thing in a
    comment. A site's stated delay is the minimum it tolerates, not a target
    to speed up to — so this is `max`, and the second and third rows are what
    distinguish a floor from "use the robots value"."""
    assert PolitenessGate.apply_robots_floor(configured_ms, robots_s) == expected_ms, why


# ---------------------------------------------------------------------------
# F14 — jitter, which is not optional
# ---------------------------------------------------------------------------


async def test_jitter_is_in_range_and_actually_varies() -> None:
    """Spec 002 §2: "Jitter is not optional. Fixed intervals are a bot
    signature."

    **Both halves.** A range assertion alone passes against a constant 1.0 —
    which is exactly no jitter, i.e. the bot signature the spec forbids. So
    this asserts the values differ, and that they are spread rather than
    clustered on one value."""
    g = PolitenessGate(clock=FakeClock(), rng=random.Random(1))
    draws = [g.jitter() for _ in range(200)]

    assert all(JITTER_MIN <= d <= JITTER_MAX for d in draws)
    assert len(set(draws)) > 150, "the jitter is not varying — a constant would pass a range check"
    assert min(draws) < 0.8 and max(draws) > 1.2, "the distribution does not reach its ends"


async def test_the_next_eligible_time_is_jittered_rather_than_exact() -> None:
    """The gap the supplier sees, not just the multiplier. A gate that
    computed jitter and then ignored it would pass the test above."""
    g = PolitenessGate(clock=FakeClock(), rng=random.Random(3))
    gaps = {
        (g.on_success(state(crawl_delay_ms=10_000)).next_eligible_at - FIXED_NOW) for _ in range(40)
    }
    assert len(gaps) > 30, "every success produced the same gap, so the jitter is unused"
    exact = timedelta(milliseconds=9000)
    assert exact not in gaps or len(gaps) > 1


async def test_the_gate_never_sleeps() -> None:
    """It returns a time; the worker waits. A gate that slept would hold a
    claim — and therefore the domain's `in_flight` gate — for the whole
    politeness delay, which ADR-0026 says a crawler cannot do."""
    g = gate()
    for call in (g.on_success, g.on_rate_limited, g.on_forbidden, g.on_server_error):
        decision = call(state())
        assert decision.next_eligible_at > FIXED_NOW
