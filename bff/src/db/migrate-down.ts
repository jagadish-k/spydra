// ADR-0024: one step back for the ui chain — drizzle-kit has no downgrade
// command. Resolves the last applied migration from drizzle's ledger +
// meta/_journal.json, runs its hand-written down.sql in a transaction,
// deletes the ledger row on success. Fails loudly on an unknown journal
// shape rather than guessing across a drizzle-kit version bump.
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import postgres from "postgres";

const MIGRATIONS_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "drizzle",
);

type JournalEntry = { when: number; tag: string };

function parseJournal(raw: unknown): JournalEntry[] {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("meta/_journal.json: not an object");
  }
  const journal = raw as Record<string, unknown>;
  if (journal.dialect !== "postgresql") {
    throw new Error(
      `meta/_journal.json: unknown dialect ${String(journal.dialect)}`,
    );
  }
  if (!Array.isArray(journal.entries)) {
    throw new Error("meta/_journal.json: entries is not an array");
  }
  return journal.entries.map((entry, i) => {
    if (typeof entry !== "object" || entry === null) {
      throw new Error(`meta/_journal.json: entry ${i} is not an object`);
    }
    const { when, tag } = entry as Record<string, unknown>;
    if (typeof when !== "number" || typeof tag !== "string") {
      throw new Error(
        `meta/_journal.json: entry ${i} has unknown shape (want {when: number, tag: string})`,
      );
    }
    return { when, tag };
  });
}

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL is not set");
  process.exit(1);
}

const journal = parseJournal(
  JSON.parse(
    await readFile(join(MIGRATIONS_DIR, "meta", "_journal.json"), "utf8"),
  ),
);
const sql = postgres(url, { max: 1 });

try {
  const rows = await sql`
    select id, hash, created_at
    from drizzle.__drizzle_migrations
    order by created_at desc
    limit 1
  `.catch((err: { code?: string }) => {
    // 42P01 undefined_table: no ledger = nothing has ever been applied.
    if (err.code === "42P01") return [];
    throw err;
  });

  const last = rows[0];
  if (!last) {
    console.log("migrate:down: nothing to roll back — ledger is empty");
  } else {
    const appliedAt = Number(last.created_at);
    const entry = journal.find((candidate) => candidate.when === appliedAt);
    if (!entry) {
      throw new Error(
        `ledger row created_at=${appliedAt} matches no journal entry — refusing to guess`,
      );
    }
    const downSql = await readFile(
      join(MIGRATIONS_DIR, `${entry.tag}.down.sql`),
      "utf8",
    );
    await sql.begin(async (tx) => {
      await tx.unsafe(downSql);
      await tx`delete from drizzle.__drizzle_migrations where created_at = ${entry.when}`;
    });
    console.log(`migrate:down: rolled back ${entry.tag}`);
  }
} finally {
  await sql.end();
}
