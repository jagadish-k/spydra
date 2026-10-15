import { defineConfig } from "drizzle-kit";

// ADR-0021 §2: crawl is introspected, never hand-written. This is the
// read-only mirror of drizzle.config.ts — same database, filtered to crawl,
// writing into a gitignored scratch dir. scripts/write-crawl-generated.ts
// then banners and copies the result to src/db/schema/crawl.generated.ts.
// The out dir is deliberately NOT under ./drizzle: tests/drizzle-guard.test.ts
// walks that tree and forbids any mention of crawl there.
export default defineConfig({
  dialect: "postgresql",
  schemaFilter: ["crawl"],
  out: "./.crawl-introspect",
  dbCredentials: { url: process.env.DATABASE_URL! },
});
