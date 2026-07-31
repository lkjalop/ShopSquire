import os
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.taxonomy_registry import (
    add_sold_node,
    ensure_tables,
    upsert_classification,
)


@pytest.fixture
def grounded_laptop_catalog():
    sku = "OPEN-NQE-1"
    with db_session() as db:
        ensure_tables(db)
        add_sold_node(db, node_handle="el-6-6", tenant_id="default")
        db.execute(
            text(
                "INSERT OR REPLACE INTO products "
                "(id, sku, name, price_cents, currency, specs, active) "
                "VALUES (:sku, :sku, 'Open-ended test laptop', 99900, "
                "'USD', '{\"ram_gb\": 16}', 1)"
            ),
            {"sku": sku},
        )
        db.execute(
            text(
                "INSERT OR REPLACE INTO inventory "
                "(id, product_id, stock, warehouse) "
                "VALUES (:id, :sku, 5, 'default')"
            ),
            {"id": f"inv-{sku}", "sku": sku},
        )
        upsert_classification(
            db,
            sku=sku,
            node_handle="el-6-6",
            source="open_ended_v2_fixture",
            status="approved",
            tenant_id="default",
        )
        db.commit()
    yield
    with db_session() as db:
        db.execute(text("DELETE FROM inventory WHERE product_id = :sku"), {"sku": sku})
        db.execute(text("DELETE FROM products WHERE id = :sku"), {"sku": sku})
        db.execute(
            text(
                "DELETE FROM product_classification "
                "WHERE tenant_id = 'default' AND sku = :sku "
                "AND source = 'open_ended_v2_fixture'"
            ),
            {"sku": sku},
        )
        db.commit()


def test_open_ended_emits_model_selection_and_next_questions(grounded_laptop_catalog):
    # Tame heavy middlewares and tolerate GET errors for test stability
    os.environ["TEST_TOLERANT_GET_ERRORS"] = "1"
    os.environ["DISABLE_SECURITY_MIDDLEWARE"] = "1"

    # Build app
    from src.app.main import create_app
    app = create_app()
    client = TestClient(app)

    # Execute suggest with an open-ended query
    r = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": "u-test", "query": "I need a laptop"},
        headers={"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")},
    )
    assert r.status_code == 200
    data = r.json()
    # Response should include next_questions
    nq = data.get("next_questions")
    # V2 asks the smallest useful clarification rather than forcing the frozen
    # V1 two-question bundle.
    assert isinstance(nq, list) and len(nq) >= 1
    # V2 owns selection through the bounded core rather than exposing the
    # frozen V1 small/big provider tier.
    assert data.get("model_tier") == "core"
    trace_id = data.get("trace_id") or data.get("decision_trace_id")
    assert trace_id, "trace_id missing in response"

    # Poll query endpoint for trace events with a bounded wait.
    events = []
    for _ in range(10):
        q = client.get(
            f"/api/v1/decisions/{trace_id}/query",
            params={"include_events": "true"},
            headers={"x-api-key": os.getenv("MERCHANT_API_KEY", "local-merchant-key")},
        )
        if q.status_code == 200:
            ev = q.json().get("events")
            if isinstance(ev, list) and ev:
                events = ev
                break
        time.sleep(0.25)
    assert events, "Trace events missing after bounded poll"
    types = [e.get("event_type") for e in events]
    # Provider-tier events belonged to V1. V2 exposes ``model_tier=core`` in
    # the response and records the consequential clarification as feedback.
    assert "feedback_loop" in types, f"next questions event missing; types={types}"
