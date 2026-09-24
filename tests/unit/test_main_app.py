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


def test_reviews_jobs_route_is_registered(client):
    resp = client.get("/reviews/jobs")
    assert resp.status_code == 200


def test_lifespan_calls_create_tables_on_startup():
    with patch.object(main_module, "create_tables", AsyncMock()) as mock_create:
        with TestClient(main_module.app):
            pass
        mock_create.assert_awaited_once()
