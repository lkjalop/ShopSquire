import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.app.main import create_app
from src.app.models.db import set_engine
from src.app.models.orm import Base


@pytest.fixture()
def client():
    """Own the migration/ORM schema used by this endpoint contract.

    The API shard intentionally contains tests that swap the shared engine.
    Binding this route to a file-local StaticPool database prevents those
    unrelated engines from deciding whether NQE persistence exists.
    """
    engine = create_engine(
        "sqlite://",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE nqe_feedback_events (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                tenant_id TEXT NOT NULL,
                trace_id TEXT NOT NULL,
                question_id TEXT NOT NULL,
                variant TEXT NOT NULL,
                converted BOOLEAN NOT NULL,
                latency_ms INTEGER NOT NULL,
                answer_value TEXT,
                helpful BOOLEAN
            )
        """))
    set_engine(engine)
    app = create_app()
    app.state.engine = engine
    # This contract is about durable NQE rows, not asynchronous observer
    # persistence.  Keep the observer off this disposable StaticPool engine so
    # teardown cannot close SQLite while its background thread is still using it.
    yield TestClient(app, headers={"x-skip-observer": "1"})


def test_nqe_feedback_and_summary_endpoints(client):
    body = {
        "trace_id": "trace-nqe-1",
        "question_id": "ask_budget",
        "tenant_id": "tenant-test",
        "variant": "control",
        "converted": True,
        "latency_ms": 350,
    }
    headers = {
        "x-api-key": "local-owner-key",
        "x-tenant-id": "tenant-test",
    }
    r1 = client.post("/api/v1/recommend/nqe_feedback", json=body, headers=headers)
    assert r1.status_code == 200, r1.text
    r2 = client.get(
        "/api/v1/recommend/admin/nqe_feedback_summary?tenant_id=tenant-test&days=30",
        headers=headers,
    )
    assert r2.status_code == 200
    items = (r2.json() or {}).get("items") or []
    assert isinstance(items, list)


def test_nqe_feedback_rejects_body_tenant_override(client):
    response = client.post(
        "/api/v1/recommend/nqe_feedback",
        headers={
            "x-api-key": "local-owner-key",
            "x-tenant-id": "tenant-a",
        },
        json={
            "trace_id": "trace-cross-tenant",
            "question_id": "ask_budget",
            "tenant_id": "tenant-b",
            "converted": False,
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "cross_tenant_nqe_feedback"
