# 0029 — The committed crawl mirror is normalised, not verbatim

**Status:** Accepted · 2026-10-19
**Amends:** [ADR-0021](0021-drizzle-for-bff.md) §2 — the mirror is
post-processed rather than copied
**Relates to:** [ADR-0013](0013-generated-api-types.md) (generated artifacts
are regenerated and diffed), [`AGENTS.md`](../../AGENTS.md) rule 16

## Context

`bff/src/db/schema/crawl.generated.ts` is Drizzle's introspection of the
`crawl` schema, committed as a build artifact. ADR-0013 and rule 16 make the
contract explicit: `make check` regenerates every such artifact and **fails
on a diff**, which catches both a stale mirror and a hand edit.

That contract has one unstated premise — **the generator must be a function
of its inputs.** `drizzle-kit introspect` is not. It is a function of the
_database_, and in two ways that both reached CI:

1. **Declaration order follows the catalog, i.e. OID order**, which is an
   artifact of each database's history rather than of the schema. `domains`
   came out second on a dev volume that had been migrated up and down a few
   times, and **last** on a freshly created one — same migration, same
   schema, different file. So `make check` passed locally and failed in CI,
   whose only difference was a clean volume.

2. **Index operator classes are mis-assigned across multi-column indexes.**
   Reproduced on drizzle-kit 0.31.11: an index's opclasses are zipped onto
   its columns in the wrong order. One run claimed
   `ix_crawl_queue_domain_pending`'s `state` column (TEXT) was `int8_ops`;
   another claimed `one_active_per_pattern`'s `domain_id` (BIGINT) was
   `text_ops`. **Both outputs are wrong**, and which way they are wrong is
   unstable.

Either one makes `generated-check` a coin flip, and a gate that fails at
random is worse than no gate: the first thing anyone does with it is learn to
re-run it until it passes.

## Decision

**`bff/scripts/write-crawl-generated.ts` normalises the introspection before
committing it.** The mirror is a normalised projection of the schema, not a
verbatim copy of a tool's output. Three transforms, in `normalize()`:

1. **Declarations are sorted** — enums first, then tables, then views, each
   group ordered by export name using code-unit comparison (not
   `localeCompare`, which would reintroduce a machine dependency).

   Enums must precede tables because a table body _calls_ its enum eagerly.
   Table-to-table references may point forward: their foreign keys live in a
   lazy `(table) => [...]` callback, which is why plain alphabetical order is
   safe for the table group. Verified with `tsc --noEmit` against a build in
   which the referenced table was declared last.

2. **`.op("…")` is dropped entirely.** It is wrong, it is unstable, and
   nothing reads it: this file exists so the BFF can `SELECT` from `crawl`
   with typed queries, an operator class is a DDL concern, and `crawl`'s DDL
   belongs to Alembic (ADR-0021). Committing a wrong annotation because a
   tool emitted it is worse than omitting it.

3. **The pg-core import list is rebuilt, sorted.** It follows declaration
   order otherwise, so it inherits the same instability.

The preamble — the imports, the `bytea` custom type, and
`export const crawl = pgSchema("crawl")` that everything references — is left
in place; only what follows is reordered.

**`make generated-check` now prints the diff it is failing on**, and says
that a diff on a machine which changed nothing means the generator is not a
function of its inputs. The failure that produced this ADR reported only
`M bff/src/db/schema/crawl.generated.ts`, which is true and useless.

## Consequences

- **`make check` is reproducible across databases.** Proved rather than
  argued: the file generated from the old, well-used dev volume and the file
  generated from a fresh one are byte-identical after normalisation, and
  `bff/tests/crawl-generated.test.ts` holds that with two captures of one
  schema reduced to exactly the differences that occurred.
- **The transforms are tested, not merely observed.** Six assertions on
  `normalize` — including idempotence, since a transform that is not a fixed
  point fails on its second run for no reason — and two on `withBytea`.
- **The writer is import-safe.** It wrote the artifact as a side effect of
  being imported, so the first test run silently overwrote the mirror. Its
  work now happens in `main()`, guarded by an `argv[1]` check.
- **Cost: the mirror no longer matches what `drizzle-kit introspect` prints.**
  Anyone comparing the two by eye will see reordered declarations and missing
  `.op()` calls and may think the file is stale. That is why the diff is
  printed and this ADR is named in the failure message.
- **Cost: one more thing between a tool and a committed file.** The writer is
  now ~90 lines of text processing rather than a copy with a banner. It earns
  that by being the only alternative to an unreliable gate, and it is
  covered by tests that run in every environment.
- **Cost: if drizzle-kit fixes the opclass bug, this keeps dropping the
  correct values.** Accepted — nothing reads them. Revisit when something
  does, which would mean this file generating DDL, which ADR-0021 forbids.

## Alternatives considered

**Pin drizzle-kit and accept the output.** Rejected: the version is already
pinned by the lockfile and both failures occurred _at_ that pin. Order
instability is a property of the database, not of the release.

**Drop `crawl.generated.ts` from `generated-check`.** Rejected — it converts
a flaky gate into no gate, and rule 16 exists because a hand-edited generated
file is how a schema boundary quietly rots.

**Normalise inside `generated-check` before diffing.** Rejected: it would
hide genuine drift behind the same transform that hides the noise, and the
committed artifact would still be the unstable text.

**Stop committing the mirror and generate it at build time.** Rejected for
now — it is the honest long-term answer to a generated file, but it is a
change to ADR-0013's model for _every_ generated artifact, not just this one,
and it would make the BFF's typecheck depend on a live database.
