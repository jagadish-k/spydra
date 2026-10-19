"""Ports: `typing.Protocol` classes at the four boundaries ADR-0008 names,
plus Clock.

A fifth port is added when its second implementation appears, not in
anticipation of it (ADR-0008 § Consequences).
"""

from .clock import Clock
from .fetcher import Fetcher
from .frontier import ClaimedUrl, Completion, Frontier, QueueItemState

__all__ = [
    "ClaimedUrl",
    "Clock",
    "Completion",
    "Fetcher",
    "Frontier",
    "QueueItemState",
]
