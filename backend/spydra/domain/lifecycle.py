"""The domain lifecycle: a pure (state, event) -> state function (spec 001 §2).

No I/O, no repository, no clock. A transition is decided here and persisted
by whoever called it, which is what lets every edge be tested without a
database.

Invalid transitions raise `InvalidTransition`. Spec 001 §2 is explicit that
they are not silently ignored, and the reason is concrete: a swallowed
ACTIVE -> PAUSED is a domain that keeps fetching after three 403s, which is
the failure ADR-0004 exists to prevent.
"""

from typing import Final

from .enums import DomainEvent, DomainState
from .errors import InvalidTransition

# Every legal edge, once. Read as: in this state, this event moves you there.
#
# Mirrors the diagram in spec 001 §2. ARCHIVE is handled below rather than
# repeated in six rows — "any -> archived" is one rule, and writing it six
# times is six places for it to rot.
_EDGES: Final[dict[tuple[DomainState, DomainEvent], DomainState]] = {
    (DomainState.DISCOVERED, DomainEvent.PROPOSE): DomainState.AWAITING_APPROVAL,
    (DomainState.AWAITING_APPROVAL, DomainEvent.APPROVE): DomainState.ACTIVE,
    # Reject returns the domain to DISCOVERED, where it can be re-proposed:
    # the proposal was wrong, the host is still a candidate.
    (DomainState.AWAITING_APPROVAL, DomainEvent.REJECT): DomainState.DISCOVERED,
    (DomainState.ACTIVE, DomainEvent.PAUSE): DomainState.PAUSED,
    (DomainState.ACTIVE, DomainEvent.BLOCK): DomainState.PAUSED,
    (DomainState.ACTIVE, DomainEvent.BREAK): DomainState.BROKEN,
    # ADR-0030 requires this edge and spec 001 §2's diagram does not draw
    # it: a first run whose template never matched goes back through
    # review, not to `broken`. Without the edge the accepted ADR's own
    # prescription raises InvalidTransition at the moment it fires — on a
    # newly approved domain, which is when an operator is watching.
    (DomainState.ACTIVE, DomainEvent.NEVER_MATCHED): DomainState.AWAITING_APPROVAL,
    (DomainState.PAUSED, DomainEvent.RESUME): DomainState.ACTIVE,
    # A broken domain does not resume: its template stopped matching the site,
    # so it goes back through approval rather than straight back to crawling
    # (spec 001 §2). This is the edge that stops a redesign being waved through.
    (DomainState.BROKEN, DomainEvent.RE_REVIEW): DomainState.AWAITING_APPROVAL,
}

# ARCHIVE is legal from anywhere except ARCHIVED itself, which is terminal.
_ARCHIVABLE: Final[frozenset[DomainState]] = frozenset(DomainState) - {DomainState.ARCHIVED}


def transition(state: DomainState, event: DomainEvent) -> DomainState:
    """The state `event` moves `state` to.

    Raises:
        InvalidTransition: if the edge does not exist. Includes the state and
            the event, because "invalid transition" alone in a log tells you
            nothing you can act on.
    """
    if event is DomainEvent.ARCHIVE:
        if state not in _ARCHIVABLE:
            raise InvalidTransition(state, event)
        return DomainState.ARCHIVED

    try:
        return _EDGES[(state, event)]
    except KeyError:
        raise InvalidTransition(state, event) from None


def can(state: DomainState, event: DomainEvent) -> bool:
    """Whether `transition` would succeed.

    Exists so the API can answer "which actions does this domain offer" from
    the same table the transition uses, rather than from a second list in the
    router that drifts from this one.
    """
    if event is DomainEvent.ARCHIVE:
        return state in _ARCHIVABLE
    return (state, event) in _EDGES


def legal_events(state: DomainState) -> frozenset[DomainEvent]:
    """Every event this state accepts."""
    return frozenset(e for e in DomainEvent if can(state, e))
