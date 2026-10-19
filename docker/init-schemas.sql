-- Spydra schema + role bootstrap (spec 010 §3, ADR-0015).
--
-- Runs once on first boot of a fresh pgdata volume (docker entrypoint
-- initdb.d). The grants ARE the data-ownership boundary: stated in a
-- document they are a convention, stated here they are an error message.
--
-- The accepted proof (BUILD_PLAN 0.7, spec 010 §6): an INSERT into
-- crawl.runs from spydra_bff must fail at the database. `make
-- verify-grants` demonstrates it.
--
-- Note on `ui`: this file does NOT create it. The BFF's first Drizzle
-- migration does, so spydra_bff OWNS the schema rather than merely holding
-- privileges on a schema someone else made. Two reasons, both verified on
-- PG 18 (ADR-0024 §discovered):
--   1. drizzle-kit's migrator runs CREATE SCHEMA IF NOT EXISTS for its
--      ledger schema unconditionally, and PG 18 checks CREATE ON DATABASE
--      for that statement even when the schema already exists — so the BFF
--      role needs database-level CREATE regardless.
--   2. drizzle-kit generate emits CREATE SCHEMA "ui" in migration 0000;
--      a pre-created ui here would make that migration fail (duplicate
--      schema) on every fresh boot.
-- Database-level CREATE does not weaken the crawl boundary: it grants no
-- rights inside existing schemas owned by others. spydra_bff still cannot
-- write a single row of crawl.

-- Roles are cluster-wide, so they are created here, once, before either
-- database is bootstrapped. Everything that is per-database — the crawl
-- schema and every grant — lives in docker/crawl-bootstrap.sql and is
-- included below and again by 20-test-db.sql. One description of the
-- boundary, applied to both databases (phase-1 finding F2).

CREATE ROLE spydra_api LOGIN PASSWORD 'spydra';
CREATE ROLE spydra_bff LOGIN PASSWORD 'spydra';

\i /bootstrap/crawl-bootstrap.sql
