"""Healthz: the phase-0 liveness probe (BUILD_PLAN 0.8).

Liveness only — the process answers, and it answers 200 even when the
database is down. Readiness semantics arrive in phase 3 (spec 010 §4);
conflating them here would make a db blip kill a healthy container.
"""

import os
from contextlib import suppress
from typing import Literal

import asyncpg
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

# The compose convention (spec 010 §3) is the SQLAlchemy dialect URL; asyncpg
# wants the plain scheme, so database_reachable normalises it away.
_DEFAULT_DATABASE_URL = "postgresql+asyncpg://spydra_api:spydra@db:5432/spydra"
_CONNECT_TIMEOUT_S = 2.0


class Health(BaseModel):
    status: Literal["ok"]
    db: Literal["ok", "down"]


async def database_reachable(url: str) -> bool:
    dsn = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    try:
        # Any failure — DNS, refused, timeout, auth — means "down"; a health
        # probe has no error worth distinguishing yet.
        conn = await asyncpg.connect(dsn=dsn, timeout=_CONNECT_TIMEOUT_S)
    except Exception:
        return False
    try:
        return bool(await conn.fetchval("SELECT 1") == 1)
    finally:
        with suppress(Exception):  # closing an already-broken conn must not fail the probe
            await conn.close()


@router.get("/healthz")
async def healthz() -> Health:
    url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
    db_ok = await database_reachable(url)
    return Health(status="ok", db="ok" if db_ok else "down")
