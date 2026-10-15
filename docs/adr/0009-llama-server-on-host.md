# 0009 — llama-server runs natively on the host

**Status:** Accepted · 2026-10-15

## Context

Everything else in this project runs in Docker (ADR-0010). The model is the
exception, and the reason is hardware: **Docker Desktop on macOS has no Metal
GPU passthrough.** A containerised `llama.cpp` runs on CPU inside a Linux VM
and loses most of the advantage of the Mac Studio Ultra it was chosen for.

## Decision

`llama-server` runs natively on the host, bound to `127.0.0.1:8080`.
Containers reach it at `host.docker.internal:8080`, configured via
`LLM_BASE_URL` and declared in compose with
`extra_hosts: ["host.docker.internal:host-gateway"]`.

The operator is responsible for starting it. The application treats it as an
external dependency: the sidebar shows its reachability, and the API returns a
clear error when a proposal is requested while it is down.

```sh
llama-server -m ~/models/<model>.gguf \
  --host 127.0.0.1 --port 8080 \
  --ctx-size 16384 --n-gpu-layers 999
```

## Consequences

- The model runs with Metal acceleration and the unified memory the hardware
  was bought for.
- Swapping models does not touch the application lifecycle.
- Because inference is once-per-template (ADR-0005), even the CPU fallback
  would technically work — but there is no reason to accept it.
- **Cost:** this is the one piece of the stack `make up` cannot bring up, so
  the environment is not fully reproducible from the repository. The
  mitigation is that its absence degrades onboarding only, never crawling,
  and the UI says so plainly. Document the setup in `docs/DEVELOPMENT.md` and
  do not pretend the container could host it.
