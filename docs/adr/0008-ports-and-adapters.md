# 0008 — Ports and adapters at four boundaries only

**Status:** Accepted · 2026-10-15

## Context

The codebase has a handful of decisions that are plausible candidates for
reversal — the queue (ADR-0002), the fetch mechanism, the model, where assets
live. It also has a great deal of ordinary code that will never be swapped.

Applying hexagonal architecture everywhere produces an interface per class and
a codebase where nothing can be read without three jumps. Applying it nowhere
means the reversible decisions are welded in.

## Decision

Ports exist at exactly four boundaries, defined as `typing.Protocol` classes
in `backend/spydra/ports/`:

| Port | Adapters | Why it exists |
| --- | --- | --- |
| `Frontier` | `PostgresFrontier` | Makes ADR-0002 reversible |
| `Fetcher` | `HttpxFetcher`, `RenderServiceFetcher` | Two real implementations, selected per domain (ADR-0016) |
| `LLMClient` | `LlamaServerClient` | Swap models or compare against a hosted API |
| `AssetStore` | `LocalAssetStore` | Storage location is config, not code |

Plus `Clock`, which exists so time-dependent scheduler logic is testable
without sleeping.

Everything else — repositories for pages, templates, runs; the extraction
chain; validation — is ordinary code in `adapters/postgres/` and
`extraction/`. No interface, no indirection.

Rules: `domain/` imports nothing from `adapters/`. The API layer talks to
ports and repositories, never to `asyncpg` directly.

## Consequences

- The four decisions most likely to change are isolated behind one file each.
- `Fetcher` is the proof the abstraction works: two adapters ship in phase 1
  precisely because a port with one implementation is an untested guess.
- Tests substitute fakes at these four seams and use the real database
  everywhere else.
- **Cost:** a judgement call about what deserves a port, and the judgement
  will sometimes be wrong. When a fifth boundary earns one, add it — but add
  it when the second implementation appears, not in anticipation of it.
