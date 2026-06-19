"""TraceBatchMiddleware wiring: a batch is opened for the recommend path and PROPAGATES to the
(threadpool-run) sync route — and is NOT opened for other paths (scoped blast radius)."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.platform.trace_batch_middleware import TraceBatchMiddleware
from src.app.services.decision_log import _TRACE_BATCH


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TraceBatchMiddleware)

    @app.get("/api/v1/recommend/probe")
    def rec():  # sync → runs in threadpool (the ContextVar propagation trap)
        return {"batch_active": _TRACE_BATCH.get() is not None}

    @app.get("/other/probe")
    def other():
        return {"batch_active": _TRACE_BATCH.get() is not None}

    return app


def test_recommend_path_opens_batch_visible_to_sync_route():
    c = TestClient(_app())
    assert c.get("/api/v1/recommend/probe").json()["batch_active"] is True


def test_non_recommend_path_not_batched():
    c = TestClient(_app())
    assert c.get("/other/probe").json()["batch_active"] is False
