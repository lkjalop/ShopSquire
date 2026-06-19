"""Request-boundary acceptance: StoreProfileMiddleware scopes the active vertical per request and
the ContextVar PROPAGATES to a (threadpool-run) SYNC route.

This is the test that proves the #1 implementation risk is handled: a naive FastAPI dependency or a
BaseHTTPMiddleware would set the ContextVar in a different task and the sync endpoint would silently
read the default (electronics). The pure-ASGI middleware must make the header-selected vertical
visible to the sync route — and must not leak across requests.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.platform.store_profile import active_profile_id
from src.app.platform.store_profile_middleware import StoreProfileMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(StoreProfileMiddleware)

    @app.get("/sync-profile")
    def sync_profile():           # sync → runs in threadpool (the propagation trap)
        return {"active": active_profile_id()}

    @app.get("/async-profile")
    async def async_profile():    # async → same task
        return {"active": active_profile_id()}

    return app


@pytest.fixture(autouse=True)
def _no_env_profile(monkeypatch):
    monkeypatch.delenv("STORE_PROFILE_ID", raising=False)


def test_header_selects_vertical_on_sync_route():
    c = TestClient(_app())
    assert c.get("/sync-profile").json()["active"] == "electronics"  # no header → default
    assert c.get("/sync-profile", headers={"X-Store-Profile": "pharmacy"}).json()["active"] == "pharmacy"
    assert c.get("/sync-profile", headers={"X-Store-Profile": "fashion"}).json()["active"] == "fashion"


def test_header_selects_vertical_on_async_route():
    c = TestClient(_app())
    assert c.get("/async-profile", headers={"X-Store-Profile": "pharmacy"}).json()["active"] == "pharmacy"


def test_env_default_when_no_header(monkeypatch):
    monkeypatch.setenv("STORE_PROFILE_ID", "fashion")
    c = TestClient(_app())
    assert c.get("/sync-profile").json()["active"] == "fashion"  # env is the deployment-level default


def test_no_leak_between_requests():
    c = TestClient(_app())
    assert c.get("/sync-profile", headers={"X-Store-Profile": "pharmacy"}).json()["active"] == "pharmacy"
    # the next request WITHOUT the header must NOT inherit pharmacy
    assert c.get("/sync-profile").json()["active"] == "electronics"
