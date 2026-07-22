from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from starlette.responses import StreamingResponse

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


def test_chat_sse_bypasses_response_capture():
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/v1/chat/stream")
    async def stream():
        async def frames():
            yield "event: thinking\ndata: {}\n\n"
            yield "event: done\ndata: {}\n\n"
        return StreamingResponse(frames(), media_type="text/event-stream")

    client = TestClient(app)
    response = client.post(
        "/api/v1/chat/stream", headers={"Idempotency-Key": "shared-stream-query-key"},
    )
    assert response.status_code == 200
    assert "event: thinking" in response.text
    middleware = app.middleware_stack.app
    assert isinstance(middleware, IdempotencyMiddleware)
    assert middleware.cache == {}


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


def _mk_app(calls):
    from fastapi import FastAPI, Request
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/v1/payments/intent")
    def intent(request: Request, amount: int = 0):
        calls["n"] += 1
        return {"amount": amount, "who": request.headers.get("x-api-key")}
    return app


def test_idempotency_is_namespaced_by_principal(tmp_path):
    # GPT-5.6 review-11b #1: two DIFFERENT callers reusing the same key must NOT cross-replay.
    import src.app.models.db as db_module
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'idem.sqlite'}", future=True)
    original = db_module.engine
    db_module.set_engine(engine)
    calls = {"n": 0}
    try:
        client = TestClient(_mk_app(calls))
        a = client.post("/api/v1/payments/intent?amount=100", headers={"Idempotency-Key": "K", "x-api-key": "A"})
        b = client.post("/api/v1/payments/intent?amount=200", headers={"Idempotency-Key": "K", "x-api-key": "B"})
        assert a.json()["amount"] == 100 and b.json()["amount"] == 200   # no cross-replay
        assert calls["n"] == 2                                            # both executed
    finally:
        db_module.set_engine(original)


def test_query_param_change_is_a_conflict_not_a_replay(tmp_path):
    # /payments/intent takes amount as a QUERY param — a body-only fingerprint replayed the wrong
    # charge. Same key + different query for the same caller must 409, never silently replay.
    import src.app.models.db as db_module
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'idem2.sqlite'}", future=True)
    original = db_module.engine
    db_module.set_engine(engine)
    calls = {"n": 0}
    try:
        client = TestClient(_mk_app(calls))
        x = client.post("/api/v1/payments/intent?amount=100", headers={"Idempotency-Key": "K2", "x-api-key": "A"})
        y = client.post("/api/v1/payments/intent?amount=200", headers={"Idempotency-Key": "K2", "x-api-key": "A"})
        assert x.status_code == 200 and x.json()["amount"] == 100
        assert y.status_code == 409                                       # different request, same key
    finally:
        db_module.set_engine(original)


def test_idempotency_composes_tenant_and_principal(tmp_path):
    import src.app.models.db as db_module
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'idem-tenant.sqlite'}", future=True)
    original = db_module.engine
    db_module.set_engine(engine)
    calls = {"n": 0}
    try:
        client = TestClient(_mk_app(calls))
        common = {"Idempotency-Key": "SHARED", "x-api-key": "platform-key"}
        a = client.post("/api/v1/payments/intent?amount=100",
                        headers={**common, "x-tenant-id": "tenant-a"})
        b = client.post("/api/v1/payments/intent?amount=100",
                        headers={**common, "x-tenant-id": "tenant-b"})
        replay = client.post("/api/v1/payments/intent?amount=100",
                             headers={**common, "x-tenant-id": "tenant-a"})
        assert a.status_code == b.status_code == replay.status_code == 200
        assert calls["n"] == 2
    finally:
        db_module.set_engine(original)


def test_lease_reclaim_kills_409_forever(tmp_path):
    # M2: a critical-path request whose owner "dies" mid-flight leaves the reservation; a retry gets
    # 409 while the lease is live, then RECLAIMS + executes once the lease expires (not 409 forever).
    import src.app.models.db as db_module
    from fastapi import FastAPI, Request
    from sqlalchemy import text as _text
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path/'lease.sqlite'}", future=True)
    original = db_module.engine
    db_module.set_engine(engine)
    calls = {"n": 0}
    app = FastAPI()
    app.add_middleware(IdempotencyMiddleware)

    @app.post("/api/v1/payments/charge")
    def charge(request: Request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("owner died mid-flight")
        return {"ok": True, "n": calls["n"]}

    client = TestClient(app, raise_server_exceptions=False)
    hdrs = {"Idempotency-Key": "K", "x-api-key": "A"}
    try:
        r1 = client.post("/api/v1/payments/charge", headers=hdrs)
        assert r1.status_code == 500 and calls["n"] == 1          # owner died; reservation LEFT (critical)

        r2 = client.post("/api/v1/payments/charge", headers=hdrs)
        assert r2.status_code == 409 and calls["n"] == 1          # live lease → in-progress, not re-run

        with db_module.db_session() as db:                        # expire the lease (owner dead)
            db.execute(_text("UPDATE idempotency_keys SET lease_expires_at = 0"))
            db.commit()

        r3 = client.post("/api/v1/payments/charge", headers=hdrs)
        assert r3.status_code == 200 and r3.json()["ok"] and calls["n"] == 2   # RECLAIMED + executed
    finally:
        db_module.set_engine(original)
