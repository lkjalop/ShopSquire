"""Flag-ON proof that Hippograph feedback reaches the V2 response as advisory evidence.

The archived V1 path injected recall into ``NextQuestionEngine``. Production compatibility routing
now uses V2, whose lexicographic ranker and clarification contract deliberately do not enroll graph
recall as authority. This locks the current honest boundary: recall is visible in the response but
does not silently nudge results without a separately authorized live experiment.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import app
from src.app.models.db import db_session
from src.app.services.recommendations import RecommendationService
from src.app.services.taxonomy_registry import (
    add_sold_node,
    search_nodes,
    upsert_classification,
)
from tests.taxonomy_helpers import apply_taxonomy_migration
from tests.utils import default_headers, write_feature_flags

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
_SENTINEL = [{"id": "GAM-HOT", "kind": "product", "label": "Hot Pick", "score": 9.9, "reward_weight": 5.0}]

client = TestClient(app, headers=default_headers())


@pytest.fixture()
def feedback_on(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_MODE", "skip")
    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._default_llm_fn",
        lambda _prompt, _timeout: "",
    )
    orig = RecommendationService.retrieve_candidates
    RecommendationService.retrieve_candidates = lambda self, q, limit=10: []
    orig_flags = open(_FLAGS_PATH, encoding="utf-8").read() if os.path.isfile(_FLAGS_PATH) else None
    write_feature_flags({
        "USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False, "DEGRADATION": {"enabled": True},
        "HIPPOGRAPH_FEEDBACK_ENABLED": True,
    })
    laptop_nodes = search_nodes("Laptops", limit=1)
    assert laptop_nodes, "pinned taxonomy does not contain the laptop fixture node"
    laptop_node = laptop_nodes[0]
    sold_node_added = False
    with db_session() as db:
        apply_taxonomy_migration(db)
        db.execute(text("INSERT OR REPLACE INTO products (id,sku,name,price_cents,currency,specs,active) "
                        "VALUES ('HGW-1','HGW-1','HG Laptop',119900,'AUD','{}',1)"))
        db.execute(text("INSERT OR REPLACE INTO inventory (id,product_id,stock,warehouse) "
                        "VALUES ('inv-hgw1','HGW-1',5,'default')"))
        existing_sold = db.execute(
            text(
                "SELECT 1 FROM sold_taxonomy "
                "WHERE tenant_id='default' AND node_handle=:node_handle"
            ),
            {"node_handle": laptop_node.handle},
        ).fetchone()
        assert upsert_classification(
            db,
            sku="HGW-1",
            node_handle=laptop_node.handle,
            source="test_fixture",
            confidence=1.0,
            status="approved",
            approved_by="test",
        )
        if not existing_sold:
            assert add_sold_node(
                db,
                node_handle=laptop_node.handle,
                source="test_fixture",
                approved_by="test",
            )
            sold_node_added = True
        db.commit()
    # Patch the recall builder to a sentinel — isolates the kv→state.kv→NQEInput wiring from data.
    monkeypatch.setattr(
        "src.app.services.hippograph_feedback.build_hippograph_insights",
        lambda *a, **k: list(_SENTINEL),
    )
    yield
    RecommendationService.retrieve_candidates = orig
    if orig_flags is not None:
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            f.write(orig_flags)
    with db_session() as db:
        db.execute(text("DELETE FROM inventory WHERE product_id='HGW-1'"))
        db.execute(text("DELETE FROM products WHERE id='HGW-1'"))
        db.execute(
            text(
                "DELETE FROM product_classification "
                "WHERE tenant_id='default' AND sku='HGW-1'"
            )
        )
        if sold_node_added:
            db.execute(
                text(
                    "DELETE FROM sold_taxonomy "
                    "WHERE tenant_id='default' AND node_handle=:node_handle "
                    "AND source='test_fixture'"
                ),
                {"node_handle": laptop_node.handle},
            )
        db.commit()


def test_feedback_reaches_response_without_becoming_v2_ranking_authority(feedback_on):
    # Keep this projection proof independent of taxonomy onboarding. Hosted
    # migration-first databases contain no product classifications until a
    # tenant supplies them, so query the fixture-owned catalog identity.
    r = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": "hgw-user", "query": "HG Laptop", "budget_max": 1500},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("hippograph_insights") == _SENTINEL
    assert not body.get("ranking_experiment")
    assert all(
        "_nudge_delta" not in row
        for row in (body.get("products") or body.get("results") or [])
        if isinstance(row, dict)
    )
