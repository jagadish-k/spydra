# 0013 — Frontend API types are generated from OpenAPI

**Status:** Accepted · 2026-10-15 · extended by [ADR-0015](0015-service-topology.md)

> There are now two OpenAPI schemas — the Python API's and the BFF's. Both
> generate into the SPA (`api/schema.crawler.d.ts`, `api/schema.ui.d.ts`)
> under the same rule: generated, committed, never hand-edited.

## Context

The backend already describes itself: FastAPI derives an OpenAPI schema from
Pydantic models. Hand-writing matching TypeScript interfaces duplicates that
description, and the duplicate drifts — usually silently, usually discovered
when a field renamed on the server reaches the UI as `undefined`.

## Decision

`make types` runs `openapi-typescript` against the running API and writes
`frontend/src/api/schema.d.ts`. That file is **generated, committed, and never
hand-edited**. A thin typed client wraps `fetch` using those types.

`make check` fails if regenerating produces a diff, so a backend schema change
that was not propagated breaks the build rather than the UI.

## Consequences

- One definition of the contract, in Pydantic, where validation already lives.
- A renamed or retyped field is a TypeScript compile error, not a runtime
  surprise.
- The spec in `docs/specs/005-api.md` stays prose-level; the schema is the
  machine-readable truth.
- **Cost:** the generator needs a running API, so `make types` depends on the
  stack being up — awkward in CI, handled by starting the API in the check
  job. Generated types are also uglier than hand-written ones, and the thin
  client exists to keep that ugliness out of components.
