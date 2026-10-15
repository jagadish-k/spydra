# Spydra api — FastAPI control plane on Python 3.15 (ADR-0017: pinned by
# major.minor). NO browser and NO playwright package here: rendering is an
# HTTP sidecar (ADR-0016).
FROM python:3.15-slim

# uv, pinned to the version that generated backend/uv.lock.
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /usr/local/bin/

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependencies only. The spydra package source arrives with task 0.8 and is
# imported from the bind mount via PYTHONPATH — never `pip install .`, which
# would fight the bind mount (ADR-0010). The venv baked here seeds the `venv`
# named volume on first run (a bind at /app would otherwise shadow it).
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen

EXPOSE 8000
