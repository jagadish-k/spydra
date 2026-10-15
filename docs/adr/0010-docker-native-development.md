# 0010 — All development runs in Docker

**Status:** Accepted · 2026-10-15

## Context

This project is built mostly by agents, across sessions, on a machine that
also does other work. "Works on my machine" is not a recoverable state when
the machine is a fresh container with no memory of the last session.

The stack also has real version sensitivity: Postgres 17 for the queue
semantics, a specific Playwright/Chromium pairing, Python 3.12, Node 22.

## Decision

Every command runs in a container, invoked through a `make` target. The
repository contains no instructions that begin "first install".

- `backend`, `worker`, `web` and `db` are compose services.
- Source is bind-mounted for hot reload; dependency directories
  (`node_modules`, the Python venv) live in **named volumes**, never on the
  bind mount.
- `make check` is exactly what CI runs.

The single exception is `llama-server` (ADR-0009).

## Consequences

- A new agent runs `make up` and has a working stack, with no host state to
  diverge.
- Version drift between contributors is structurally impossible.
- CI and local are the same commands.
- **Cost, and it is real:** bind-mount filesystem performance on macOS is
  poor, file watching needs polling (`usePolling` in Vite, `--reload-dir` for
  uvicorn), and iteration is slower than running natively. Node and Python
  dependency directories *must* stay in named volumes or the host's
  platform-specific binaries will fight the container's. These are known
  frictions, documented in `docs/DEVELOPMENT.md`, and accepted in exchange for
  reproducibility.
