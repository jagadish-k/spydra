# 0013 — Frontend API types are generated from OpenAPI

**Status:** Accepted · 2026-10-15

> Two OpenAPI schemas are generated — the Python API's and the BFF's
> ([ADR-0015](0015-service-topology.md)) — into
> `frontend/src/api/schema.crawler.d.ts` and `frontend/src/api/schema.ui.d.ts`,
> under one rule: generated, committed, never hand-edited.

## Context

The backend already describes itself: FastAPI derives an OpenAPI schema from
Pydantic models. Hand-writing matching TypeScript interfaces duplicates that
description, and the duplicate drifts — usually silently, usually discovered
when a field renamed on the server reaches the UI as `undefined`.

## Decision

`make types` runs `openapi-typescript` and writes
`frontend/src/api/schema.crawler.d.ts` and `frontend/src/api/schema.ui.d.ts`.
Those files are **generated, committed, and never hand-edited**. A thin typed
client wraps `fetch` using those types.

`make check` fails if regenerating produces a diff, so a backend schema change
that was not propagated breaks the build rather than the UI.

## Consequences

- One definition of the contract, in Pydantic, where validation already lives.
- A renamed or retyped field is a TypeScript compile error, not a runtime
  surprise.
- The spec in `docs/specs/005-api.md` stays prose-level; the schema is the
  machine-readable truth.
- **Cost:** the generator needs the API's OpenAPI document, so `make types`
  exports it by importing the app inside the container (no listener, no ports
  — works in CI on a clean checkout). Generated types are also uglier than
  hand-written ones, and the thin client exists to keep that ugliness out of
  components.
