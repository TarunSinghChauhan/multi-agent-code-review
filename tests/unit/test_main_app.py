from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import src.api.main as main_module


@pytest.fixture
def client():
    with patch.object(main_module, "create_tables", AsyncMock()):
        with TestClient(main_module.app) as c:
            yield c


def test_health_route_is_registered(client):
    resp = client.get("/health/")
    assert resp.status_code == 200


def test_listing_all_jobs_is_not_exposed(client):
    # GET /reviews/jobs was removed on purpose: job ids are the only access control
    # on results, so the demo must not list them.
    assert client.get("/reviews/jobs").status_code == 404


def test_limits_route_is_registered(client):
    resp = client.get("/reviews/limits")
    assert resp.status_code == 200
    assert set(resp.json()) == {"daily_limit", "used_today", "remaining_today", "max_code_chars"}


def test_lifespan_calls_create_tables_on_startup():
    with patch.object(main_module, "create_tables", AsyncMock()) as mock_create:
        with TestClient(main_module.app):
            pass
        mock_create.assert_awaited_once()
