"""ADR-0030's arithmetic (BUILD_PLAN 1.11).

The counting query is tested against real rows in
`tests/adapters/postgres/test_observations.py`. This file is the comparison,
where the boundary can be hit exactly: "21% trips it and 19% does not" is a
claim about arithmetic, and asserting it through a database means asserting
it through whatever that query happened to count.
"""

import pytest

from spydra.domain.enums import DomainEvent, DomainState
from spydra.domain.health import RunHealth, assess
from spydra.domain.lifecycle import transition


def health(
    *, pages: int, regressions: int = 0, empty: int | None = None, first_run: bool = False
) -> RunHealth:
    """`empty` defaults to `regressions`, because a regression IS an empty
    page with a prior — a call that set them independently by accident would
    describe a run that cannot exist."""
    return RunHealth(
        pages_crawled=pages,
        regressions=regressions,
        empty_pages=regressions if empty is None else empty,
        first_run=first_run,
    )


# ---------------------------------------------------------------------------
# The threshold itself — BUILD_PLAN 1.11's "21% trips it while 19% does not"
# ---------------------------------------------------------------------------


def test_21_percent_trips_the_threshold() -> None:
    assert assess(health(pages=100, regressions=21)) is DomainEvent.BREAK


def test_19_percent_does_not() -> None:
    assert assess(health(pages=100, regressions=19)) is None


def test_20_percent_exactly_does_not() -> None:
    """ADR-0030 says `> 0.20`, so the boundary is NOT a halt.

    Asserted because this is the comparison binary floating point gets a vote
    on if the ratio is computed in floats, and the direction of that vote
    decides whether a domain halts.
    """
    assert assess(health(pages=100, regressions=20)) is None


@pytest.mark.parametrize(
    ("pages", "regressions"),
    [(5, 2), (7, 2), (10, 3), (50, 11)],
)
def test_small_runs_use_the_same_ratio(pages: int, regressions: int) -> None:
    """A 5-page run with 2 regressions is 40% and halts.

    Small runs are where an integer-rounded implementation goes wrong: `2 //
    5 * 100` is 0, and a domain with 40% of its catalogue dead would keep
    crawling.
    """
    assert assess(health(pages=pages, regressions=regressions)) is DomainEvent.BREAK


@pytest.mark.parametrize("pages", [0, 1, 2, 3, 4])
def test_one_regression_never_halts_a_domain_on_its_own(pages: int) -> None:
    """The verdict is re-read after every page (spec 003 §3 halts mid-run), so
    on a run's first page the ratio is one page over one page.

    Measured during `1.11`: a five-page run whose FIRST page was its one
    redesigned page halted the domain at 100%, two pages before the same run
    settled at 20% — a state that needs a human to clear (ADR-0004). Below
    five pages one page is always over 20%, so five is where a single page
    stops being a verdict. Zero pages is the same guard, which is also why
    the division is never reached.
    """
    assert assess(health(pages=pages, regressions=min(pages, 1))) is None
    assert assess(health(pages=pages, regressions=pages)) is None


def test_the_minimum_sample_does_not_hide_a_whole_catalogue(pages: int = 5) -> None:
    """The pair with the test above: at five pages the ratio is live again,
    so the guard delays a verdict rather than suppressing one."""
    assert assess(health(pages=5, regressions=2)) is DomainEvent.BREAK
    assert (
        assess(health(pages=5, regressions=0, empty=2, first_run=True)) is DomainEvent.NEVER_MATCHED
    )


# ---------------------------------------------------------------------------
# ADR-0030's distinction: a soft 404 is not evidence of a regression
# ---------------------------------------------------------------------------


def test_empty_pages_without_priors_do_not_halt_an_established_domain() -> None:
    """The reason ADR-0030 exists. A catalogue where 80% of pages are dead
    links reports 80 empty pages and no regressions, and keeps crawling —
    before the ADR it halted itself on every run and reported a redesign
    that never happened."""
    assert assess(health(pages=100, regressions=0, empty=80)) is None


def test_a_single_regression_among_many_soft_404s_is_still_counted() -> None:
    """The ratio is over pages crawled, not over empty pages — so dead links
    cannot dilute a real regression out of existence. 2 of 5 is 40%."""
    assert assess(health(pages=5, regressions=2, empty=4)) is DomainEvent.BREAK


# ---------------------------------------------------------------------------
# The first run: "this never worked" is not "this stopped working"
# ---------------------------------------------------------------------------


def test_a_first_run_past_the_threshold_goes_back_to_review() -> None:
    """ADR-0030: a template approved against three samples that fails against
    the catalogue is not a redesign. Nothing has a prior, so `regressions` is
    0 and the empty count is what is read."""
    assert (
        assess(health(pages=100, regressions=0, empty=21, first_run=True))
        is DomainEvent.NEVER_MATCHED
    )


def test_a_healthy_first_run_is_left_alone() -> None:
    assert assess(health(pages=100, regressions=0, empty=19, first_run=True)) is None


def test_a_first_run_never_reports_a_regression() -> None:
    """Defence in depth. On a first run no page CAN have a prior, so a
    non-zero `regressions` is a bug in the query — and if one ever arrives,
    the right answer is still `awaiting_approval`, not a halt that claims
    something used to work."""
    assert (
        assess(health(pages=100, regressions=99, empty=99, first_run=True))
        is DomainEvent.NEVER_MATCHED
    )


# ---------------------------------------------------------------------------
# Both events have to be reachable from where the domain actually is
# ---------------------------------------------------------------------------


def test_both_verdicts_are_legal_edges_out_of_active() -> None:
    """The anti-vacuity control for this slice's lifecycle change.

    A domain under assessment is `ACTIVE` — that is the only state that
    crawls (spec 001 §2). Before this slice, accepted ADR-0030's own
    prescription had no edge: `active -> awaiting_approval` is in neither
    `lifecycle.py` nor spec 001 §2's diagram, so `NEVER_MATCHED` would have
    raised `InvalidTransition` the first time a newly approved domain missed
    on its catalogue. A threshold that returns an unreachable event is a
    detector that crashes instead of firing.
    """
    assert transition(DomainState.ACTIVE, DomainEvent.BREAK) is DomainState.BROKEN
    assert (
        transition(DomainState.ACTIVE, DomainEvent.NEVER_MATCHED) is DomainState.AWAITING_APPROVAL
    )


def test_the_two_verdicts_are_not_the_same_destination() -> None:
    """ADR-0030's whole point: "this used to work and stopped" and "this
    never worked" stop sharing one state."""
    assert transition(DomainState.ACTIVE, DomainEvent.BREAK) is not transition(
        DomainState.ACTIVE, DomainEvent.NEVER_MATCHED
    )
