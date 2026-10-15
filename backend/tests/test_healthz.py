from fastapi.testclient import TestClient

from spydra.api.main import create_app


def test_healthz_is_alive_and_reports_db() -> None:
    client = TestClient(create_app())
    response = client.get("/api/crawler/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # No DB in the test environment — "down" is the expected reading, and the
    # endpoint is liveness-only, so 200 either way.
    assert body["db"] in {"ok", "down"}


def test_smoke_sse_streams_six_frames() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/api/crawler/__smoke/sse")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        frames = [line for line in response.text.splitlines() if line.startswith("data:")]
    assert len(frames) == 6
    assert frames[0].startswith('data: {"seq": 0')
    assert frames[5].startswith('data: {"seq": 5')
