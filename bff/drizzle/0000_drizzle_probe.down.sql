-- Hand-written per ADR-0024: the down half of 0000_drizzle_probe. This
-- migration created the ui schema itself (the init grants shape of
-- docker/init-schemas.sql cannot survive drizzle-kit — see the 0.10 handoff
-- log), so its exact inverse drops the schema, not just the probe table.
-- Dropping only the table would leave `CREATE SCHEMA "ui"` in the up file
-- colliding on re-apply and break the migrate → down → migrate invariant CI
-- asserts. Later migrations drop their own objects, never the schema.
DROP SCHEMA IF EXISTS ui CASCADE;
