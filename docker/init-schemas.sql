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

CREATE SCHEMA crawl;   -- owned by api/worker, migrated by Alembic

CREATE ROLE spydra_api LOGIN PASSWORD 'spydra';
CREATE ROLE spydra_bff LOGIN PASSWORD 'spydra';

GRANT USAGE, CREATE ON SCHEMA crawl TO spydra_api;
GRANT CREATE ON DATABASE spydra TO spydra_bff;   -- creates ui + drizzle ledger itself

-- The BFF may READ crawl data for aggregation, never write it. It starts a
-- crawl by calling POST /api/crawler/runs, never by inserting a runs row.
GRANT USAGE ON SCHEMA crawl TO spydra_bff;
ALTER DEFAULT PRIVILEGES FOR ROLE spydra_api IN SCHEMA crawl
  GRANT SELECT ON TABLES TO spydra_bff;

-- The API gets no access to ui at all: no grant, no route in, nothing.
-- Deliberately the last line — the absence below is the assertion.
