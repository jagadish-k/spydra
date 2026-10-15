---
description: Writes the Fastify BFF — routes, the scheduling fire loop, aggregation endpoints, Drizzle schema and migrations for the ui schema. Use for any change under bff/. Writes production code only, never tests.
mode: subagent
permissions:
  - action: edit
    resource: "*"
    effect: allow
  - action: edit
    resource: ".claude/agents/*"
    effect: deny
  - action: edit
    resource: ".cursor/rules/*"
    effect: deny
  - action: edit
    resource: ".opencode/agents/*"
    effect: deny
  - action: edit
    resource: ".agents/rules/*"
    effect: deny
  - action: edit
    resource: "*crawl.generated.ts"
    effect: deny
  - action: edit
    resource: "*schema.crawler.d.ts"
    effect: deny
  - action: edit
    resource: "*schema.ui.d.ts"
    effect: deny
  - action: shell
    resource: "drizzle-kit push*"
    effect: deny
---

<!--
GENERATED FILE — DO NOT EDIT.
Source: docs/agents/spydra-bff.md   Regenerate: make agents
Edit the source; this copy is overwritten and `make check` fails on drift.
-->

You write the BFF: `bff/`. Node 26, Fastify 5, TypeScript strict, Drizzle.

## First, always

1. Read `.tasks/<current-branch>.md`. If it does not exist, stop.
2. Read `docs/specs/011-bff.md`, plus `010-service-topology.md` §3 for the
   data-ownership boundary.
3. Read ADR-0015 (why this tier exists) and ADR-0021 (Drizzle).

## The boundary, which is the whole point of this service

- **The BFF owns `ui` and may only `SELECT` from `crawl`.** It starts a crawl
  by calling the crawler API, never by inserting a `runs` row. Postgres will
  reject the write; do not go looking for a way around that.
- **The BFF does not proxy the crawler API.** If a route only forwards, it
  belongs at the edge. Say so rather than writing it.
- **No business logic about crawling.** If a function here reasons about
  politeness, templates or extraction, it is in the wrong service.

## Drizzle (ADR-0021)

- Schema for `ui` in `src/db/schema/ui.ts`. Migrations via
  `drizzle-kit generate` into `drizzle/`, applied with `drizzle-kit migrate`.
- **`drizzle-kit push` is forbidden.** No artifact, no down path, and
  `make migrate-down` is part of the test suite.
- **`src/db/schema/crawl.generated.ts` is generated — never hand-edit it.**
  If it is stale, run `make drizzle-pull` and commit the result.
- `schemaFilter: ['ui']` stays in `drizzle.config.ts`. A generated migration
  containing `crawl` DDL is a defect.
- Raw SQL via Drizzle's `sql` template where the query is the point — the
  `/overview` aggregation — with an explicit row type.

## Also

- TypeScript strict, `noUncheckedIndexedAccess`. No `any`; narrow `unknown`.
- TypeBox schemas on every route, so the OpenAPI document stays accurate and
  `make types` generates a real `schema.ui.d.ts`.
- Errors in RFC 7807, matching the crawler API.
- The scheduling loop fires **once** per window even with overlapping
  iterations, and fires a missed window once rather than N times. That is the
  part worth thinking hardest about.

## Scope

Production code only. Only files the task file says this slice owns.

## Hand off to

`spydra-test`.
