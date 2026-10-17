-- The integration-test database (TESTING.md §1, phase-1 finding F2).
--
-- Runs after 10-schemas.sql on first boot of a fresh pgdata volume, so the
-- cluster-wide roles already exist. Same schema, same grants, same
-- ownership boundary as `spydra` — see docker/crawl-bootstrap.sql for why
-- that sameness is the point and not just convenience.
--
-- Migrations are NOT run here. backend/tests/conftest.py brings this
-- database to alembic head once per session: the suite owns its own schema
-- state, so a developer who adds a migration does not have to remember to
-- reset a volume before the tests see it.
--
-- template0 rather than the default template1: nothing should be able to
-- leak into the test database by being installed into template1 later.

CREATE DATABASE spydra_test TEMPLATE template0 ENCODING 'UTF8';

\connect spydra_test

\i /bootstrap/crawl-bootstrap.sql
