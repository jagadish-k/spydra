"""Domain exceptions.

Raised from `domain/`, translated to HTTP in `api/` (AGENTS.md § Conventions).
Nothing here knows about status codes.
"""

from .enums import DomainEvent, DomainState


class SpydraError(Exception):
    """Base for everything this package raises."""


class InvalidTransition(SpydraError):
    """An illegal lifecycle move.

    Spec 001 §2: invalid transitions raise; they are not silently ignored. A
    silently ignored transition is how a domain stays ACTIVE after three 403s.
    """

    def __init__(self, state: DomainState, event: DomainEvent) -> None:
        self.state = state
        self.event = event
        super().__init__(f"{event.value!r} is not a legal event in state {state.value!r}")


class Backpressure(SpydraError):
    """The far side is full; this is not a fetch failure.

    Spec 002 §6: a 503 from the render sidecar means its queue is full. The
    row returns to `pending` and `consecutive_failures` is NOT incremented —
    counting it as a failure would walk a healthy domain toward a pause
    (ADR-0004) because our own sidecar was busy.

    It is part of the Fetcher contract rather than a detail of one adapter, so
    that 1.6's tests do not change when 1.7 lands.
    """


class FetchFailed(SpydraError):
    """A fetch that did not produce a response: DNS, refused, timeout."""


class RefusedConfiguration(SpydraError, ValueError):
    """A configuration file asks for something the system will not do
    (BUILD_PLAN 1.14): a required field (ADR-0027), a seed on another host, or
    reactivating a domain the lifecycle says only a human may move."""
