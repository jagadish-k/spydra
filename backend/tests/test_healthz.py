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
    # The __smoke/sse route is covered by tests/test_smoke_sse.py (0.17),
    # which subsumes the weaker check that used to live here.
