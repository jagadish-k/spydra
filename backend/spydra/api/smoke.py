# Scaffolding for the BUILD_PLAN 0.6 edge-unbuffered proof. DELETED by task 3.6
# (real SSE endpoint arrives there). Do not extend.
#
# The path is `runs/__smoke/events` deliberately: it has to match the
# Caddyfile's `handle /api/crawler/runs/*/events`, which is the only handle
# carrying `flush_interval -1`. Under the old `__smoke/sse` the proof was
# served by the general `handle /api/crawler/*` and so measured Caddy's
# default behaviour rather than the two lines spec 010 §2 calls load-bearing
# (phase-0 audit, F2).

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

_EVENT_COUNT = 6
_INTERVAL_S = 1.0


async def _frames() -> AsyncIterator[str]:
    for seq in range(_EVENT_COUNT):
        frame = json.dumps({"seq": seq, "server_ts": datetime.now(UTC).isoformat()})
        yield f"data: {frame}\n\n"
        await asyncio.sleep(_INTERVAL_S)


@router.get("/runs/__smoke/events")
async def smoke_sse() -> StreamingResponse:
    # X-Accel-Buffering: no tells any proxy in the path not to buffer the
    # stream; the edge's flush_interval only covers our own Caddy (ADR-0012).
    return StreamingResponse(
        _frames(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
