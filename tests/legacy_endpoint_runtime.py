"""Runtime-only access to the migrated disposable pytest database."""
import pytest
from fastapi.testclient import TestClient
from src.app.main import create_app
from src.app.models.db import get_engine
from tests.utils import default_headers


@pytest.fixture
def endpoint_runtime(monkeypatch):
    monkeypatch.setenv('SECURITY_OBSERVER_SYNC', '1')
    monkeypatch.setenv('SECURITY_BLOCK_MODE', '200')
    monkeypatch.setenv('SKIP_OBSERVER_ENDPOINTS', '')
    with TestClient(create_app(), headers=default_headers()) as client:
        yield get_engine(), client
