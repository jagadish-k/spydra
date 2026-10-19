"""The domain lifecycle (spec 001 §2, §6).

Spec 001 §6 asks for every valid edge and at least three invalid ones. Both
tables below are written from the diagram in §2, not from `lifecycle.py` —
a table copied out of the implementation agrees with it by construction and
proves nothing (WORKFLOW §3, steps 3 and 4).
"""

import pytest

from spydra.domain import DomainEvent as E
from spydra.domain import DomainState as S
from spydra.domain import InvalidTransition, can, legal_events, transition

# Every edge the diagram draws, apart from "any -> archived".
VALID_EDGES = [
    (S.DISCOVERED, E.PROPOSE, S.AWAITING_APPROVAL),
    (S.AWAITING_APPROVAL, E.APPROVE, S.ACTIVE),
    (S.AWAITING_APPROVAL, E.REJECT, S.DISCOVERED),
    (S.ACTIVE, E.PAUSE, S.PAUSED),
    (S.ACTIVE, E.BLOCK, S.PAUSED),
    (S.ACTIVE, E.BREAK, S.BROKEN),
    (S.PAUSED, E.RESUME, S.ACTIVE),
    (S.BROKEN, E.RE_REVIEW, S.AWAITING_APPROVAL),
]

INVALID_EDGES = [
    # Terminal means terminal. Nothing leaves ARCHIVED, including a second
    # archive.
    (S.ARCHIVED, E.RESUME),
    (S.ARCHIVED, E.ARCHIVE),
    (S.ARCHIVED, E.PROPOSE),
    # Approval is not skippable: a domain cannot go live without a reviewed
    # template, which is the guarantee the whole approval gate exists for.
    (S.DISCOVERED, E.APPROVE),
    # A broken domain does not simply resume — its template stopped matching
    # the site, so it goes back through approval (spec 001 §2). This is the
    # edge whose absence stops a redesign being waved through.
    (S.BROKEN, E.RESUME),
    # Only an ACTIVE domain sends requests, so only an ACTIVE domain can be
    # blocked or broken by a response.
    (S.PAUSED, E.BLOCK),
    (S.ARCHIVED, E.BREAK),
    (S.AWAITING_APPROVAL, E.PAUSE),
]


@pytest.mark.parametrize(("state", "event", "expected"), VALID_EDGES)
def test_valid_edges(state: S, event: E, expected: S) -> None:
    assert transition(state, event) is expected


@pytest.mark.parametrize("state", [s for s in S if s is not S.ARCHIVED])
def test_archive_is_legal_from_every_other_state(state: S) -> None:
    """ "any -> archived" is one rule, so it is tested as one."""
    assert transition(state, E.ARCHIVE) is S.ARCHIVED


@pytest.mark.parametrize(("state", "event"), INVALID_EDGES)
def test_invalid_edges_raise(state: S, event: E) -> None:
    with pytest.raises(InvalidTransition) as caught:
        transition(state, event)
    # The message has to name both, because "invalid transition" alone in a
    # log tells an operator nothing they can act on.
    assert state.value in str(caught.value)
    assert event.value in str(caught.value)
    assert caught.value.state is state
    assert caught.value.event is event


def test_archived_is_terminal() -> None:
    assert legal_events(S.ARCHIVED) == frozenset()


def test_three_403s_and_an_operator_pause_are_different_events_on_one_edge() -> None:
    """ADR-0004's auto-pause and an operator pause share a destination.

    They are deliberately separate events: the run report has to distinguish
    "you stopped this" from "the site refused us three times", and a
    lifecycle keyed on state pairs alone could not.
    """
    assert transition(S.ACTIVE, E.BLOCK) is transition(S.ACTIVE, E.PAUSE)
    # Same destination, two events — and both are offered on an active domain,
    # so the distinction survives into what the API will expose.
    assert {E.BLOCK, E.PAUSE} <= legal_events(S.ACTIVE)


@pytest.mark.parametrize("state", list(S))
def test_can_agrees_with_transition(state: S) -> None:
    """`can` is what the API answers "which actions does this domain offer"
    from, so it has to be the same table the transition uses rather than a
    second list that drifts."""
    for event in E:
        if can(state, event):
            assert transition(state, event) in S
        else:
            with pytest.raises(InvalidTransition):
                transition(state, event)


@pytest.mark.parametrize("state", list(S))
def test_legal_events_matches_can(state: S) -> None:
    assert legal_events(state) == frozenset(e for e in E if can(state, e))


def test_only_active_crawls() -> None:
    """Spec 001 §2: a domain that is not ACTIVE sends no requests, which is
    what makes "block until I approve" cheap."""
    from datetime import UTC, datetime

    from spydra.domain import Domain, RenderMode
    from spydra.domain.ids import DomainId

    def at(state: S) -> Domain:
        return Domain(
            id=DomainId(1),
            host="example.test",
            state=state,
            render_mode=RenderMode.STATIC,
            crawl_delay_ms=2000,
            max_concurrency=1,
            asset_concurrency=5,
            respect_robots=True,
            next_eligible_at=datetime(2026, 10, 17, tzinfo=UTC),
            consecutive_failures=0,
        )

    assert at(S.ACTIVE).crawls
    assert not any(at(s).crawls for s in S if s is not S.ACTIVE)
