// The ui schema, owned by the BFF and migrated by drizzle-kit (ADR-0021).
// pgSchema("ui") is what makes every generated DDL statement schema-qualified
// — the property the CI guard in tests/drizzle-guard.test.ts asserts on.
import { pgSchema, serial, timestamp } from "drizzle-orm/pg-core";

export const ui = pgSchema("ui");

// BUILD_PLAN 0.10: a throwaway table proving generate → migrate →
// migrate-down end to end. It carries nothing; delete it (up + down pair)
// when the first real table lands in phase 3.
export const drizzleProbe = ui.table("drizzle_probe", {
  id: serial("id").primaryKey(),
  createdAt: timestamp("created_at", { withTimezone: true })
    .defaultNow()
    .notNull(),
});
