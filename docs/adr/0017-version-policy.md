# 0017 — Track latest versions, behind a readiness gate

**Status:** Accepted · 2026-10-15

## Context

The operator wants the newest versions of everything, and the project is
docker-native so the runtime is pinned in images rather than inherited from a
host. That makes aggressive version tracking cheap to adopt and cheap to
revert — but it is not free of risk, and the risk is concentrated in one
place: **compiled Python wheels after a new CPython release.**

Python 3.15.0 was released on 2026-10-09. A project adopting it six days
later is betting that `asyncpg`, `Pillow`, `selectolax` and `pydantic-core`
have published `cp315` wheels. If they have not, the Docker build either
compiles from source — slowly, and needing a toolchain in the image — or
fails.

That bet was checked rather than assumed. As of 2026-10-15:

| Package | Version | `cp315` wheels |
| --- | --- | --- |
| `asyncpg` | 0.32.0 (2026-10-06) | yes, incl. free-threaded `cp315t` |
| `Pillow` | 12.3.0 (2026-07-01) | yes |
| `selectolax` | 1.0.0 (2026-10-03) | yes |

Moving Playwright out of the Python process (ADR-0016) removed the dependency
most likely to lag a CPython release.

## Decision

**Target the latest stable release of every component.** Current targets:

| Component | Version | Note |
| --- | --- | --- |
| Python | 3.15 | Released 2026-10-09 |
| PostgreSQL | 18 | Current stable |
| Node | 26 | Current; enters Active LTS ~2026-10-20 |
| React | 19 | |
| Fastify | 5 | |
| Tailwind | 4 | CSS-first config (ADR-0018) |

Governed by three rules:

1. **Lockfiles are the truth.** `uv.lock` and `package-lock.json` hold exact
   versions. Documentation names major versions only; a doc that pins a patch
   is a doc that is wrong within a week.
2. **A new major is adopted only when the readiness gate passes:** every
   compiled dependency publishes a wheel for the target interpreter, and
   `make check` is green. Verify on PyPI before changing a base image — do
   not discover it in a failing build.
3. **Pin base images by major.minor**, never `:latest`. `python:3.15-slim`,
   `postgres:18`, `node:26-slim`. Reproducibility matters more than being
   current to the patch, and Dependabot handles the rest.

**Node 26 over Node 24** despite 24 being Active LTS for a few more days: 26
takes over within the week, and starting a greenfield project on an LTS line
that is about to go maintenance is choosing a migration for no benefit.

## Consequences

- The stack is current, and the docker-native constraint means a bad bump is
  one image tag away from reverted.
- Free-threaded Python (`cp315t`) becomes a realistic future experiment for
  the worker, since the dependencies already ship it. **Not now** — it is not
  needed and it would be a second thing to debug.
- **Cost, and it is real:** newest means thinnest community knowledge. A
  Python 3.15 behaviour change or a Tailwind v4 edge case will have fewer
  Stack Overflow answers than the version before it. Budget time for
  first-encounter problems that an older stack would not have.
- **A quarterly bump is a scheduled task, not a background wish.** Bump, run
  `make check`, read the changelogs for the majors, revert what breaks.
  Without the ritual, "latest" silently becomes "whatever we started on".
