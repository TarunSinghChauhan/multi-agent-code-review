from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routers import health as health_module


def test_health_returns_timezone_aware_utc_timestamp():
    app = FastAPI()
    app.include_router(health_module.router, prefix="/health")

    resp = TestClient(app).get("/health/")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "multi-agent-code-review"
    parsed = datetime.fromisoformat(body["timestamp"])
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)
