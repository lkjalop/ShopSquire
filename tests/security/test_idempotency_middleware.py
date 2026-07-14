from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

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
