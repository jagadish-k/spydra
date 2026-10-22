"""Postgres adapters. Raw SQL where the query is the point (AGENTS.md).

`PostgresFrontier` is the queue (ADR-0002), and its claim query carries the
politeness guarantee in SQL rather than in process memory (ADR-0026).
"""

from .frontier import PostgresFrontier

__all__ = ["PostgresFrontier"]
