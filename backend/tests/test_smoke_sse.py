"""Unit tests for the SSE smoke route (BUILD_PLAN 0.17, spec 010 §2).

Headers are asserted on a streamed request so they are checked before the
body: no need to wait out the stream just to read a header. The frame test
reads the full real stream (~6s — six frames at 1s intervals). That is
deliberate: no mocked clock, no patched interval; correctness over speed
for a smoke route.
"""

import json
import re

from fastapi.testclient import TestClient

from spydra.api.main import app

client = TestClient(app)

_SMOKE_URL = "/api/crawler/__smoke/sse"


def test_smoke_sse_declares_event_stream_and_disables_proxy_buffering() -> None:
    # X-Accel-Buffering: no is the standard signal to any proxy in the path
    # not to buffer the stream (ADR-0012); the edge flush line only covers
    # our own Caddy.
    with client.stream("GET", _SMOKE_URL) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["x-accel-buffering"] == "no"


def test_smoke_sse_streams_six_frames_seq_0_to_5_and_closes_cleanly() -> None:
    # Full read takes ~6s (six frames, 1s apart) — accepted, see module
    # docstring. Completing the read without a timeout or a raised server
    # exception IS the "closes cleanly" assertion; TestClient surfaces both.
    with client.stream("GET", _SMOKE_URL) as response:
        body = "".join(response.iter_text())

    # The whole body is exactly six `data: {json}\n\n` frames and nothing
    # else — a truncated or extra-frame stream fails here.
    assert re.fullmatch(r"(data: \{[^\n]*\}\n\n){6}", body), body

    frames = [json.loads(m) for m in re.findall(r"data: (\{[^\n]*\})\n\n", body)]
    assert [frame["seq"] for frame in frames] == list(range(6))
