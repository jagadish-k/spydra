"""The politeness gate (spec 002 §2, §4; ADR-0004).

**This is the component ADR-0004 was written for.** The operator named being
blocked as the worst outcome, and the standard HTTP client behaviour — retry
with backoff — is exactly wrong against a block: a site that has decided to
refuse you reads continued requests as confirmation that you are a bot, and
a temporary rate-limit becomes a permanent ban.

So the hard rule is negative. **Nothing here retries a 403.** A 403 counts,
and three consecutive ones stop the domain.

**The gate computes; it does not persist.** Every method returns values —
`1.8`'s frontier writes them in the same transaction that closes the queue
row, which is the dual-write problem ADR-0002 chose Postgres to avoid. `1.8`
has a test asserting no politeness arithmetic appears in its SQL; this module
is the other side of that assertion.
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from spydra.ports.clock import Clock

log = logging.getLogger(__name__)

# Spec 002 §2. Fixed intervals are a bot signature; ±30% is cheap and removes
# the regularity. Both ends matter: a jitter that only ever slowed down would
# drift a crawl later and later, and one that only sped up would breach the
# configured delay.
JITTER_MIN = 0.7
JITTER_MAX = 1.3

# ADR-0004 / spec 002 §4.
BACKOFF_FACTOR = 2
BACKOFF_CAP_MS = 15 * 60 * 1000

# Spec 002 §4: "decay crawl_delay_ms toward its configured value by 10% per
# success, never below it".
DECAY_FACTOR = 0.9

# ADR-0004: three consecutive 403s pause the domain.
BLOCK_THRESHOLD = 3


@dataclass(frozen=True, slots=True)
class DomainPoliteness:
    """The politeness state of one domain, as the gate sees it.

    Carried rather than read from the database on every decision so the
    arithmetic is pure and testable. `1.13` loads it with the claim and hands
    the result back to the frontier.

    `floor_ms` is the configured delay the decay may not go below — and it is
    a parameter rather than a column because **there is no column**. See the
    task file's open question: `domains.crawl_delay_ms` is a single value, so
    the ×2 backoff destroys whatever the operator configured and spec 002
    §4's "never below it" has nothing to refer to.
    """

    crawl_delay_ms: int
    consecutive_failures: int = 0
    consecutive_403s: int = 0
    floor_ms: int = 2000


@dataclass(frozen=True, slots=True)
class Decision:
    """What the gate decided about one fetch outcome.

    `pause_domain` and `abandon_queue` travel together — ADR-0004 stops the
    domain *and* records the work it did not do, because "the abandoned rows
    stay in the queue marked `abandoned` so the run report can show the work
    that was not done, rather than reporting a clean finish".
    """

    next_eligible_at: datetime
    crawl_delay_ms: int
    consecutive_failures: int
    consecutive_403s: int
    pause_domain: bool = False
    abandon_queue: bool = False

    @property
    def state(self) -> DomainPoliteness:
        return DomainPoliteness(
            crawl_delay_ms=self.crawl_delay_ms,
            consecutive_failures=self.consecutive_failures,
            consecutive_403s=self.consecutive_403s,
        )


class PolitenessGate:
    """Decides when a domain may next be fetched, and whether it still may.

    The `random.Random` is injected so the arithmetic can be tested exactly.
    It is **not** a licence to assert politeness with it: TESTING.md §2
    requires the gaps to be proven against observed timestamps, and a test
    that seeds this and checks the number it gets back has proven arithmetic,
    not politeness.
    """

    def __init__(self, clock: Clock, rng: random.Random | None = None) -> None:
        self._clock = clock
        self._rng = rng if rng is not None else random.SystemRandom()

    # -- the four outcomes of spec 002 §4 ---------------------------------

    def on_success(self, state: DomainPoliteness) -> Decision:
        """2xx. Reset the failure counters and decay the delay.

        Both counters reset, and that is what "consecutive" means: a 403
        followed by a success followed by two 403s must not pause the domain.
        """
        decayed = max(state.floor_ms, int(state.crawl_delay_ms * DECAY_FACTOR))
        return Decision(
            next_eligible_at=self._next_eligible(decayed),
            crawl_delay_ms=decayed,
            consecutive_failures=0,
            consecutive_403s=0,
        )

    def on_rate_limited(self, state: DomainPoliteness) -> Decision:
        """429 or 503 from a **supplier**. Back off; the domain stays active.

        Not the render sidecar's 503 — that is `Backpressure` and never
        reaches the gate (spec 002 §6, and `1.7`'s adapter raises it instead
        of returning a status).

        The 403 counter is **not** reset here. A site that rate-limits
        between refusals has not stopped refusing, and resetting would let
        403/429/403/429/403 run for ever.
        """
        backed_off = min(BACKOFF_CAP_MS, state.crawl_delay_ms * BACKOFF_FACTOR)
        return Decision(
            next_eligible_at=self._next_eligible(backed_off),
            crawl_delay_ms=backed_off,
            consecutive_failures=state.consecutive_failures + 1,
            consecutive_403s=state.consecutive_403s,
        )

    def on_forbidden(self, state: DomainPoliteness) -> Decision:
        """403. Count it. Three consecutive and the domain stops.

        **No backoff, and no retry.** ADR-0004: "Never retry through a 403."
        Backing off would be a slower retry, which is still a retry, and a
        site that has decided to refuse us reads it as confirmation.

        The 403 count is tracked separately from `consecutive_failures`
        because spec 002 §4 increments that one for 403, 429 and 503 alike.
        Reading the pause off the shared counter would pause a domain after
        one 403 and two 429s — a pause the operator did not earn, on a site
        that was merely busy.
        """
        forbidden = state.consecutive_403s + 1
        blocked = forbidden >= BLOCK_THRESHOLD
        if blocked:
            log.warning(
                "domain_blocked",
                extra={"consecutive_403s": forbidden, "threshold": BLOCK_THRESHOLD},
            )
        return Decision(
            # Unchanged: the domain is about to be paused, and if it is not
            # (fewer than three) the delay the operator configured still
            # applies. A doubled delay here would be a retry with extra steps.
            next_eligible_at=self._next_eligible(state.crawl_delay_ms),
            crawl_delay_ms=state.crawl_delay_ms,
            consecutive_failures=state.consecutive_failures + 1,
            consecutive_403s=forbidden,
            pause_domain=blocked,
            # ADR-0004: the work not done is recorded, not deleted, so the
            # run report shows it instead of reporting a clean finish.
            abandon_queue=blocked,
        )

    def on_server_error(self, state: DomainPoliteness) -> Decision:
        """5xx other than 503. **No domain-level penalty** (spec 002 §4).

        The row is retried by the frontier's own attempt count and fails
        after three; the domain is untouched. A 500 is the site being broken,
        not the site refusing us, and charging it toward a pause would stop
        crawling a domain that is merely having a bad day.
        """
        return Decision(
            next_eligible_at=self._next_eligible(state.crawl_delay_ms),
            crawl_delay_ms=state.crawl_delay_ms,
            consecutive_failures=state.consecutive_failures,
            consecutive_403s=state.consecutive_403s,
        )

    # -- the floor -------------------------------------------------------

    @staticmethod
    def apply_robots_floor(crawl_delay_ms: int, robots_delay_s: float | None) -> int:
        """`Crawl-delay` RAISES the delay and never lowers it (spec 002 §5).

        `max`, not "use the robots value": a site asking for 1 s must not
        speed up a crawler the operator configured to wait 2 s. The site's
        number is the minimum it tolerates, not a target.
        """
        if robots_delay_s is None:
            return crawl_delay_ms
        return max(crawl_delay_ms, int(robots_delay_s * 1000))

    # -- jitter ----------------------------------------------------------

    def jitter(self) -> float:
        """A multiplier in [0.7, 1.3].

        Spec 002 §2: "Jitter is not optional. Fixed intervals are a bot
        signature." Which is why the test for this asserts that successive
        values **differ** as well as that they are in range — a range check
        alone passes against a constant 1.0, i.e. against no jitter at all.
        """
        return self._rng.uniform(JITTER_MIN, JITTER_MAX)

    def _next_eligible(self, crawl_delay_ms: int) -> datetime:
        jittered_ms = crawl_delay_ms * self.jitter()
        return self._clock.now() + timedelta(milliseconds=jittered_ms)
