# 0014 — SQLAlchemy Core + Alembic, raw SQL where the query is the point

**Status:** Accepted · 2026-10-15

## Context

The database layer has two very different kinds of work. Most of it is
ordinary CRUD. A small amount of it *is* the system: the `SKIP LOCKED` claim
query, the `DISTINCT ON` current-state view, the price-change lateral join.
Those queries are the design, not an implementation detail.

An ORM makes the CRUD pleasant and the important queries unreadable. Raw
`asyncpg` everywhere makes the important queries clear and leaves migrations
to be hand-rolled.

## Decision

- **SQLAlchemy 2.0 Core** (not the ORM) with the **asyncpg** driver, for
  connection pooling, schema definition and the boring CRUD.
- **Alembic** for migrations. Every schema change ships with one, and it must
  run both up and down.
- **Raw SQL via `text()`** for the queries that carry the design. They live in
  `adapters/postgres/`, commented with what they guarantee, and are covered by
  tests against a real Postgres.

No ORM identity map, no lazy loading, no relationship graph. Repositories
return domain objects.

## Consequences

- The claim query is readable as SQL, which is how it will be reasoned about
  and debugged.
- Migrations are a solved problem rather than a directory of numbered files
  and a bespoke runner.
- **Cost:** two idioms in one layer, and a reviewer has to know which applies
  where. The rule is: if the query encodes a concurrency or correctness
  guarantee, write it as SQL; otherwise use Core. Tests run against real
  Postgres, never SQLite — `SKIP LOCKED` and `DISTINCT ON` do not exist there,
  so a SQLite test suite would be testing a different system.
