// The crawl mirror is a committed build artifact that `make check`
// regenerates and diffs (ADR-0013, ADR-0021, AGENTS.md rule 16). That is
// worthless unless the generator is a function of the SCHEMA alone — and
// drizzle-kit's introspection is not: it is a function of the database.
//
// It failed CI while the same command was green locally. These tests are
// the regression guard; ADR-0029 is the reasoning.

import assert from "node:assert/strict";
import { test } from "node:test";

import { normalize, withBytea } from "../scripts/write-crawl-generated.js";

// Two captures of ONE schema from two databases, reduced to the differences
// that actually occurred. `domains` is second in one and last in the other
// (catalog/OID order), and the multi-column index's operator classes are
// zipped onto the wrong columns, differently each time.
const FROM_A = `import { pgTable, pgSchema, text, integer, index } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"

export const crawl = pgSchema("crawl");
export const domainStateInCrawl = crawl.enum("domain_state", ['active'])

export const domainsInCrawl = crawl.table("domains", {
\tid: integer(),
\tstate: domainStateInCrawl().default('active').notNull(),

export const crawlQueueInCrawl = crawl.table("crawl_queue", {
\tdomainId: integer("domain_id"),
\tstate: text(),
}, (table) => [
\tindex("ix_q").using("btree", table.domainId.asc().op("int8_ops"), table.state.asc().op("text_ops")),
]);
`;

const FROM_B = `import { pgTable, pgSchema, index, text, integer } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"

export const crawl = pgSchema("crawl");
export const domainStateInCrawl = crawl.enum("domain_state", ['active'])

export const crawlQueueInCrawl = crawl.table("crawl_queue", {
\tdomainId: integer("domain_id"),
\tstate: text(),
}, (table) => [
\tindex("ix_q").using("btree", table.domainId.asc().op("text_ops"), table.state.asc().op("int8_ops")),
]);

export const domainsInCrawl = crawl.table("domains", {
\tid: integer(),
\tstate: domainStateInCrawl().default('active').notNull(),
`;

test("makes two databases of the same schema produce one artifact", () => {
  // The whole point. Without this, `make check` fails for anyone whose
  // database has a different history — which is how it presented: green
  // on a well-used dev volume, red in CI on a fresh one.
  assert.equal(normalize(FROM_A), normalize(FROM_B));
});

test("drops operator classes rather than committing wrong ones", () => {
  // Both captures above mis-assign them, in opposite directions. They are
  // a DDL concern, crawl's DDL belongs to Alembic (ADR-0021), and nothing
  // in the BFF reads them — so the honest artifact omits them.
  assert.ok(!normalize(FROM_A).includes(".op("));
});

test("declares enums before the tables that call them", () => {
  // A table body calls its enum eagerly, so this ordering is a
  // correctness requirement, not a style choice. Table-to-table
  // references live in a lazy `(table) => [...]` callback and may point
  // forward, which is why plain alphabetical order is safe for those.
  const out = normalize(FROM_A);
  assert.ok(out.indexOf("crawl.enum(") < out.indexOf("crawl.table("));
});

test("sorts the import names", () => {
  assert.ok(
    normalize(FROM_A).includes(
      'import { index, integer, pgSchema, pgTable, text } from "drizzle-orm/pg-core"',
    ),
  );
});

test("keeps the schema handle in the preamble, above every declaration", () => {
  // Everything references `crawl`; sorting it into the middle would be a
  // file that cannot load.
  const out = normalize(FROM_B);
  assert.ok(out.indexOf('pgSchema("crawl")') < out.indexOf("crawl.enum("));
});

test("is idempotent", () => {
  // `make check` regenerates and diffs, so a transform that is not a
  // fixed point fails on the second run for no reason.
  assert.equal(normalize(normalize(FROM_A)), normalize(FROM_A));
});

test("maps drizzle-kit's unknown() placeholder onto a declared bytea type", () => {
  // drizzle-kit has no bytea in pg-core and emits `unknown(...)`, which is
  // a TYPE used as a value — TS2693. Five crawl columns hit this, all
  // load-bearing (spec 001 §1's dedupe hashes, ADR-0007's content_hash).
  const src = `import { pgTable, pgSchema } from "drizzle-orm/pg-core"

export const crawl = pgSchema("crawl");
export const pagesInCrawl = crawl.table("pages", {
\turlHash: unknown("url_hash").notNull(),
`;
  const out = withBytea(src);
  // Judge the CODE, not the commentary: the declaration withBytea inserts
  // explains itself by naming `unknown(...)`, and an assertion over the raw
  // text fails on its own documentation.
  const code = out
    .split("\n")
    .filter((line: string) => !line.trim().startsWith("//"))
    .join("\n");
  assert.ok(!/\bunknown\(/.test(code));
  assert.ok(out.includes('bytea("url_hash")'));
  assert.ok(out.includes("customType<{ data: Buffer; driverData: Buffer }>"));
});

test("leaves a schema with no bytea columns alone", () => {
  const src = `import { pgTable } from "drizzle-orm/pg-core"\nexport const x = 1;\n`;
  assert.equal(withBytea(src), src);
});
