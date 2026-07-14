from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

import src.app.security.idempotency as idem
from src.app.security.idempotency import IdempotencyMiddleware


def test_exact_request_replays_and_changed_payload_conflicts(tmp_path):
    import src.app.models.db as db_module

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'idempotency.sqlite'}", future=True)
    original = db_module.engine
    db_module.set_engine(engine)
    calls = {"count": 0}
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/charge")
    def charge(payload: dict):
        calls["count"] += 1
        return {"charge_id": "charge-1", "amount": payload["amount"]}

    try:
        client = TestClient(app)
        headers = {"Idempotency-Key": "attempt-1"}
        first = client.post("/charge", json={"amount": 100}, headers=headers)
        replay = client.post("/charge", json={"amount": 100}, headers=headers)
        changed = client.post("/charge", json={"amount": 200}, headers=headers)

        assert first.status_code == 200
        assert replay.status_code == 200 and replay.json() == first.json()
        assert changed.status_code == 409
        assert calls["count"] == 1
    finally:
        db_module.set_engine(original)


@contextmanager
def _broken_store():
    raise RuntimeError("idempotency store down")
    yield  # pragma: no cover


def test_noncritical_path_degrades_when_store_unavailable(monkeypatch):
    # P1 hardening: a broken idempotency store must NOT block a non-money idempotent write —
    # it degrades to process-without-dedup (availability), not a hard 503 for the whole app.
    monkeypatch.setattr(idem, "db_session", _broken_store)
    calls = {"count": 0}
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/v1/notes")
    def notes(payload: dict):
        calls["count"] += 1
        return {"ok": True}

    client = TestClient(app)
    r = client.post("/api/v1/notes", json={"x": 1}, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 200 and calls["count"] == 1   # processed, not 503


def test_critical_path_fails_closed_when_store_unavailable(monkeypatch):
    # money path: a broken store must fail CLOSED (503) — never risk an un-deduped payment.
    monkeypatch.setattr(idem, "db_session", _broken_store)
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/v1/payments/intent")
    def intent(payload: dict):
        return {"ok": True}

    client = TestClient(app)
    r = client.post("/api/v1/payments/intent", json={"x": 1}, headers={"Idempotency-Key": "k1"})
    assert r.status_code == 503


def test_cache_is_bounded(monkeypatch):
    # P1 hardening: the in-memory cache was unbounded (memory leak). It now evicts oldest when full.
    monkeypatch.setenv("IDEMPOTENCY_CACHE_MAX", "64")
    mw = IdempotencyMiddleware(app=lambda scope, receive, send: None)
    for i in range(400):
        mw._cache_put(f"k{i}", {"ts": i, "body": {}, "status": 200, "fingerprint": "f"})
    assert len(mw.cache) <= 64
