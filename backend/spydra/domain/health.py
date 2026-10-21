"""The broken-template detector's arithmetic (ADR-0030, ADR-0027, spec 003 §3).

Spec 003 §3 calls what this catches "the system's most important failure
mode: it produces no error and no crash, just wrong data" — a redesign that
returns 200 and extracts nothing. BUILD_PLAN `5.6` puts it more bluntly: this
is the only thing standing between a redesign and silent data corruption.

ADR-0030, verbatim:

```
regression(page)  <=>  empty_extraction(this observation)
                       AND there is an earlier observation of this page
                           whose extraction was non-empty

broken(domain, run) <=> count(regression) / count(pages crawled) > 0.20
```

**In `domain/`, with `lifecycle.py`, and not in `observations/`.** It was
written there and moved: the Postgres adapter has to name `RunHealth` (it
produces one), the writer has to import the adapter, and the package
`__init__` re-exported both — a circular import, raised by the test run
rather than by review. The placement with no cycle is also the honest one:
this is a pure function over counts returning a `DomainEvent`, which is
`lifecycle.transition`'s shape exactly, and `domain/` is where that lives
(ADR-0008: `domain/` imports nothing from `adapters/`).

**Pure, and over three integers.** The counting is SQL
(`adapters/postgres/observations.py`); the comparison is here. So "21% trips
it and 19% does not" is arithmetic that cannot be flaky, and the query is
proven separately against real rows. A threshold tested only through its
query is tested at the mercy of whatever that query happened to count.

**A first run has no priors, so it cannot regress** — the correct answer
rather than a hole (ADR-0030 § "The first run has no priors"). An empty
extraction with no history means the template never worked, which is a
different failure with a different destination: back through review
(`awaiting_approval`), not `broken`, which means "this used to work".
"""

from dataclasses import dataclass
from typing import Final

from spydra.domain.enums import DomainEvent

# Spec 001 §2's table: ">20% of a run's pages fail validation". ADR-0027
# re-based "fail validation" on emptiness; the number is unchanged.
BROKEN_THRESHOLD_PERCENT: Final[int] = 20

# The smallest run the ratio may be read on, and it is DERIVED rather than
# picked: `1/n > 0.20` holds for every `n < 5`, so below five pages a single
# page is already over the threshold.
#
# This matters because spec 003 §3 halts a domain **mid-run**, so the ratio is
# re-read after every page — and on the first page of a run it is a ratio of
# one. Measured: a five-page run whose first page was the one redesigned page
# halted the whole domain at 100%, two pages before the same run settled at
# 20% and should not have halted at all. A false `broken` stops a domain and
# needs a human to clear it (ADR-0004 § Consequences), which is exactly the
# "loud recurring failure" ADR-0030 refused to trade for.
#
# Five is therefore the smallest sample at which one page cannot halt a
# domain on its own, which is the property wanted, not a tuning guess. Spec
# 003 §3 names no minimum: raised in
# `.tasks/feat-1.11-observation-writes.md`.
MINIMUM_PAGES_FOR_A_VERDICT: Final[int] = 5


@dataclass(frozen=True, slots=True)
class RunHealth:
    """One domain's extraction health within one run.

    Three counts, each of **distinct pages** rather than of observations: a
    retry writes a second observation of one page (`1.13`), and counting
    observations would let a domain dilute its own ratio by retrying.
    """

    pages_crawled: int
    # Empty on a 200 AND carrying an earlier non-empty observation.
    # ADR-0030's numerator.
    regressions: int
    # Empty on a 200, prior or not. Only a first run reads this, where by
    # definition no page has a prior.
    empty_pages: int
    first_run: bool


def assess(health: RunHealth) -> DomainEvent | None:
    """The event this run's health calls for, or `None` to keep crawling.

    `BREAK` -> `broken`: pages that used to extract have stopped.
    `NEVER_MATCHED` -> `awaiting_approval`: a first run in which the template
    never worked on more than a fifth of the catalogue — approved against
    three samples, met five layouts.
    """
    if health.pages_crawled < MINIMUM_PAGES_FOR_A_VERDICT:
        # Too little to read a ratio on — including zero pages, where the
        # division would not even be defined. See the constant: on a run's
        # first page the "ratio" is one page, and a domain must not halt on
        # one page of evidence.
        return None

    if health.first_run:
        if _over(health.empty_pages, health.pages_crawled):
            return DomainEvent.NEVER_MATCHED
        return None

    if _over(health.regressions, health.pages_crawled):
        return DomainEvent.BREAK
    return None


def _over(count: int, pages: int) -> bool:
    """`count / pages > 20%`, in integers.

    Integer arithmetic rather than `count / pages > 0.20`: at 20% exactly,
    binary floating point gets a vote on whether a domain halts. `21 > 20`
    has no such opinion, and the boundary is the case an operator meets.
    """
    return count * 100 > pages * BROKEN_THRESHOLD_PERCENT
