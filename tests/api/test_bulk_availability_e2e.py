"""End-to-end: a bulk B2B + availability query reaches /recommend/suggest and the response carries
the structured availability verdict AND the plain availability line on the assistant message.
Proves the full chain is wired: decompose (qty+horizon) → fast-path-exclusion → constraints →
Availability_Agent → payload.availability → assistant message.

Seeds the GAM-* gaming catalog (products + aligned inventory) first so there ARE products to assess
— with no catalog the zero-results recovery returns early (correctly) and availability is moot.
x-skip-observer avoids the cold-start observer latency.
"""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from src.app.main import create_app


def _seed_catalog(engine=None):
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from src.app.models.db import db_session
    from src.app.services.taxonomy_registry import (
        add_sold_node,
        ensure_tables,
        upsert_classification,
    )
    from scripts.seed_gaming_laptops import ensure_gaming_catalog
    session_scope = Session(engine) if engine is not None else db_session()
    with session_scope as db:
        ensure_gaming_catalog(db)
        ensure_tables(db)
        add_sold_node(db, node_handle="el-6-11-2", tenant_id="default")
        rows = db.execute(text("SELECT sku FROM products WHERE sku LIKE 'GAM-%'")).fetchall()
        for row in rows:
            upsert_classification(
                db,
                sku=str(row[0]),
                node_handle="el-6-11-2",
                source="bulk_availability_e2e",
                status="approved",
                tenant_id="default",
            )
        # The tenant test profile is AUD-authoritative. Keep this legacy seed in
        # that currency so the currency clamp, rather than an unrelated USD/AUD
        # mismatch, does not erase the availability fixture.
        db.execute(text("UPDATE products SET currency='AUD' WHERE sku LIKE 'GAM-%'"))
        db.commit()


def test_bulk_availability_query_wired_end_to_end(monkeypatch):
    monkeypatch.setenv("USE_MOCK_LLM", "1")
    monkeypatch.setenv("TASK_ALLOW_INPROCESS_FALLBACK", "0")
    # Taxonomy persistence itself has dedicated tests. This integration gate
    # isolates the quantity/horizon-to-availability wiring from SQLite's
    # cross-session schema/locking behavior.
    monkeypatch.setattr(
        "src.app.services.recommendation_core.core.grounding_status",
        lambda *args, **kwargs: "grounded",
    )
    monkeypatch.setattr(
        "src.app.services.recommendation_core.evidence.grounding_status",
        lambda *args, **kwargs: "grounded",
    )
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from src.app.models.db import set_engine
    from src.app.models.orm import Base
    engine = create_engine(
        "sqlite://", future=True, poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    set_engine(engine)
    app = create_app()
    app.state.engine = engine
    _seed_catalog()  # GAM-* gaming laptops ($1,199–1,799) WITH inventory (stock > 10)
    client = TestClient(app)
    r = client.get(
        "/api/v1/recommend/suggest",
        params={
            "uid": f"bulk-avail-e2e-{uuid.uuid4()}",
            "query": "10 gaming laptops at $1800 each, can you deliver in 4 weeks?",
        },
        headers={"x-skip-observer": "1", "x-api-key": "local-merchant-key"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    n = len(body.get("results") or body.get("products") or [])
    avail = body.get("availability")
    assert isinstance(avail, dict) and avail.get("applicable") is True, f"availability not attached (n_results={n})"
    assert avail.get("requested_qty") == 10        # bulk quantity threaded end-to-end
    assert avail.get("horizon_days") == 28          # "4 weeks" → 28 days
    assert avail.get("fulfilment") in (
        "in_stock", "reorder_within_horizon", "reorder_exceeds_horizon", "reorder_required",
    )
    msg = str(body.get("assistant_message") or body.get("message") or "").lower()
    assert "on availability" in msg                 # the plain line reached the answer
