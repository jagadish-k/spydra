"""Scheduling: the politeness gate and the claim loop.

`PolitenessGate` decides *when* a domain may be fetched and *whether* it
still may (spec 002 §2, §4; ADR-0004). `RobotsCache` reads the site's own
rules once per domain per run (§5). Neither persists anything — `1.8`'s
frontier writes what they compute, in the transaction that closes the queue
row.
"""

from .politeness import Decision, DomainPoliteness, PolitenessGate
from .robots import RobotsCache, RobotsRules

__all__ = [
    "Decision",
    "DomainPoliteness",
    "PolitenessGate",
    "RobotsCache",
    "RobotsRules",
]
