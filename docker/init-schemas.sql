-- Spydra schema + role bootstrap (spec 010 §3, ADR-0015).
--
-- Runs once on first boot of a fresh pgdata volume (docker entrypoint
-- initdb.d). The grants ARE the data-ownership boundary: stated in a
-- document they are a convention, stated here they are an error message.
--
-- The accepted proof (BUILD_PLAN 0.7, spec 010 §6): an INSERT into
-- crawl.runs from spydra_bff must fail at the database. `make
-- verify-grants` demonstrates it.

CREATE SCHEMA crawl;   -- owned by api/worker, migrated by Alembic
CREATE SCHEMA ui;      -- owned by bff,        migrated by the Node tool

CREATE ROLE spydra_api LOGIN PASSWORD 'spydra';
CREATE ROLE spydra_bff LOGIN PASSWORD 'spydra';

GRANT USAGE, CREATE ON SCHEMA crawl TO spydra_api;
GRANT USAGE, CREATE ON SCHEMA ui    TO spydra_bff;

-- The BFF may READ crawl data for aggregation, never write it. It starts a
-- crawl by calling POST /api/crawler/runs, never by inserting a runs row.
GRANT USAGE ON SCHEMA crawl TO spydra_bff;
ALTER DEFAULT PRIVILEGES FOR ROLE spydra_api IN SCHEMA crawl
  GRANT SELECT ON TABLES TO spydra_bff;

-- The API gets no access to ui at all: no grant, no route in, nothing.
-- Deliberately the last line — the absence below is the assertion.
