-- Per-DATABASE half of the crawl bootstrap. Included, never auto-run.
--
-- This file is NOT numbered and NOT mounted into
-- /docker-entrypoint-initdb.d — the entrypoint runs every *.sql it finds
-- there, and this one must run twice, once per database, rather than once.
-- It is mounted at /bootstrap/ and pulled in with \i by both
-- 10-schemas.sql (→ spydra) and 20-test-db.sql (→ spydra_test).
--
-- Why it exists (BUILD_PLAN 1.1, phase-1 finding F2): TESTING.md §1 requires
-- integration tests to run against a separate `spydra_test` database. The
-- grants here ARE the data-ownership boundary (spec 010 §3, ADR-0015) and
-- `make verify-grants` proves them on `spydra`. A test database with
-- hand-copied grants would drift from the one that gets proven, and the
-- drift would show up as a green suite on a boundary that had already moved.
-- So there is one description of the boundary and both databases get it.
--
-- Roles are cluster-wide and are created once, in 10-schemas.sql, before
-- either inclusion. Nothing here creates a role.

CREATE SCHEMA crawl; -- owned by api/worker, migrated by Alembic

GRANT USAGE, CREATE ON SCHEMA crawl TO spydra_api;

-- Database-level CREATE for the BFF so it owns `ui` and the drizzle ledger
-- outright (the reasoning is in 10-schemas.sql). Dynamic because this file
-- runs against two databases and GRANT takes no expression for the name.
DO $$
BEGIN
  EXECUTE format('GRANT CREATE ON DATABASE %I TO spydra_bff', current_database());
END
$$;

-- The BFF may READ crawl data for aggregation, never write it. It starts a
-- crawl by calling POST /api/crawler/runs, never by inserting a runs row.
GRANT USAGE ON SCHEMA crawl TO spydra_bff;
ALTER DEFAULT PRIVILEGES FOR ROLE spydra_api IN SCHEMA crawl
  GRANT SELECT ON TABLES TO spydra_bff;

-- The API gets no access to ui at all: no grant, no route in, nothing.
-- Deliberately the last line — the absence below is the assertion.
