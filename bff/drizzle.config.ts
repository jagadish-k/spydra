import { defineConfig } from "drizzle-kit";

// ADR-0021: schemaFilter is load-bearing — generate can never emit DDL for
// crawl, which Alembic owns. The ledger is drizzle's default
// drizzle.__drizzle_migrations, the table ADR-0024's runner reads.
export default defineConfig({
  schema: "./src/db/schema/ui.ts",
  out: "./drizzle",
  dialect: "postgresql",
  schemaFilter: ["ui"], // a generated migration can never touch crawl
  dbCredentials: { url: process.env.DATABASE_URL! },
});
