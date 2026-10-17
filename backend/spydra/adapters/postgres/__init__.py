"""Postgres adapters: repositories, and raw SQL where the query is the point.

**Deliberately empty.** Nothing is re-exported here. Phase 1 adds `frontier.py`
and `domains.py` from lane A and `observations.py` from lane C, in parallel —
a package that re-exported its modules would make all three lanes edit this
one file, which is the conflict ADR-0022 §5 exists to prevent. Import by
module path.
"""
