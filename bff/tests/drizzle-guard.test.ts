// ADR-0021's third guard, as CI: nothing under bff/drizzle/ may touch any
// schema but ui. Plus ADR-0024: every generated migration ships a sibling
// down.sql. Both rules are structural — they read files, never the database,
// so they run in every environment that can run npm test.
import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const DRIZZLE_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "drizzle",
);

function walk(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

const files = walk(DRIZZLE_DIR);
const upMigrations = files.filter(
  (path) => path.endsWith(".sql") && !path.endsWith(".down.sql"),
);

test("every generated migration has a sibling .down.sql (ADR-0024)", () => {
  assert.ok(upMigrations.length > 0, "no migrations found under bff/drizzle");
  for (const up of upMigrations) {
    const down = `${up.slice(0, -".sql".length)}.down.sql`;
    assert.ok(
      existsSync(down),
      `${up} has no .down.sql — a migration cannot land without its down path`,
    );
  }
});

test("nothing under bff/drizzle touches any schema but ui (ADR-0021)", () => {
  const ddlTarget =
    /\b(?<verb>create|drop|alter)\s+(?<kind>table|index|schema|view|type|sequence)\s+(?:if\s+(?:not\s+)?exists\s+)?(?<target>\S+)/gi;

  for (const path of files) {
    const content = readFileSync(path, "utf8");
    assert.doesNotMatch(
      content,
      /\bcrawl\./i,
      `${path} mentions crawl — Alembic owns that schema`,
    );
    // Comments may quote DDL when they explain it; only statements count.
    const statements = content
      .split("\n")
      .filter((line) => !line.trimStart().startsWith("--"))
      .join("\n");
    for (const match of statements.matchAll(ddlTarget)) {
      const { kind, target } = match.groups ?? {};
      // A schema DDL target is the bare name; everything else must carry
      // the ui. qualification (pgSchema("ui") makes drizzle emit it).
      const expected =
        kind?.toLowerCase() === "schema" ? /^"?ui"?(;|$)/ : /^"?ui"?\./;
      assert.match(
        target ?? "",
        expected,
        `${path}: ${match[0]} — target is not ui`,
      );
    }
  }
});
