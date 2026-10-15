# Scaffolding for the BUILD_PLAN 0.6 edge-unbuffered proof. DELETED by task 3.6
# (real SSE endpoint arrives there). Do not extend.

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


@router.get("/__smoke/sse")
async def smoke_sse() -> StreamingResponse:
    # X-Accel-Buffering: no tells any proxy in the path not to buffer the
    # stream; the edge's flush_interval only covers our own Caddy (ADR-0012).
    return StreamingResponse(
        _frames(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
