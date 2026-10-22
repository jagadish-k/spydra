"""Observation writes: the hash, the review routing and the broken detector.

BUILD_PLAN `1.11`. `writer.py` is the order the steps happen in. The SQL that
produces the counts is in `adapters/postgres/observations.py`, because
ADR-0008 puts no port here — a repository for observations is ordinary code.
ADR-0030's arithmetic is in `domain/health.py`: it is pure, both of the
others need it, and importing it from here made a cycle.
"""

from .writer import CrawledPage, ObservationWriter, WriteOutcome

__all__ = ["CrawledPage", "ObservationWriter", "WriteOutcome"]
