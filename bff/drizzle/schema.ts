import { pgTable, pgSchema, serial, timestamp } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"

export const ui = pgSchema("ui");


export const drizzleProbeInUi = ui.table("drizzle_probe", {
	id: serial().primaryKey().notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
});
