"""ASGI entrypoint: uvicorn spydra.api.main:app (compose.yaml).

Routes are mounted at /api/crawler inside the app so the edge proxies
without rewriting (spec 005 §1, spec 010 §2).
"""

from fastapi import FastAPI

from spydra.api.healthz import router as healthz_router
from spydra.api.smoke import router as smoke_router


def create_app() -> FastAPI:
    app = FastAPI()
    app.include_router(healthz_router, prefix="/api/crawler")
    app.include_router(smoke_router, prefix="/api/crawler")
    return app


app = create_app()
