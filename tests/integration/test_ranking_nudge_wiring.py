"""Flag-ON proof of the reversible ranking nudge through the experiment gate.

The first measured live adaptation, so it gets a real e2e: with the flag on + a LIVE experiment, a
TREATMENT user's hippograph-recalled product is boosted (nudged>=1); a CONTROL user is untouched
(nudged==0). The arm is forced via assign_variant so the assertion is deterministic; the boost/reorder
math itself is covered by the unit tests.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import app
from src.app.models.db import db_session
from src.app.services.experiments import ensure_tables as ensure_experiment_tables
from src.app.services.taxonomy_registry import (
    add_sold_node,
    search_nodes,
    upsert_classification,
)
from tests.experiment_helpers import apply_experiment_migrations, create_sealed_experiment
from tests.taxonomy_helpers import apply_taxonomy_migration
from tests.utils import default_headers

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
client = TestClient(
    app,
    # This suite owns experiment/ranking composition, not observer persistence.
    # Avoid a background observer transaction racing the SQLite experiment gate.
    headers={**default_headers(), "x-skip-observer": "1"},
)


def _delete_ranking_experiment(db) -> None:
    """Own this fixture's experiment rows, including legacy duplicate names."""
    experiment_ids = [
        str(row[0])
        for row in db.execute(
            text(
                "SELECT id FROM experiment_run "
                "WHERE tenant_id='default' AND name='ranking_nudge_v1'"
            )
        ).fetchall()
    ]
    for experiment_id in experiment_ids:
        db.execute(
            text(
                "DELETE FROM experiment_assignment "
                "WHERE tenant_id='default' AND experiment_id=:experiment_id"
            ),
            {"experiment_id": experiment_id},
        )
        db.execute(
            text(
                "DELETE FROM experiment_result "
                "WHERE tenant_id='default' AND experiment_id=:experiment_id"
            ),
            {"experiment_id": experiment_id},
        )
    db.execute(
        text(
            "DELETE FROM experiment_run "
            "WHERE tenant_id='default' AND name='ranking_nudge_v1'"
        )
    )


@pytest.fixture()
def nudge_stack(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_MODE", "skip")
    monkeypatch.setattr(
        "src.app.services.recommendation_core.turn_router._default_llm_fn",
        lambda _prompt, _timeout: "",
    )
    # This suite characterizes ranking authorization, not account metering.
    # Developer .env files may deliberately enable durable token budgets, so
    # own the boundary here rather than inheriting prior local Redis usage.
    monkeypatch.setenv("TOKEN_BUDGET_ENABLED", "false")
    orig_flags = open(_FLAGS_PATH, encoding="utf-8").read() if os.path.isfile(_FLAGS_PATH) else None
    with open(_FLAGS_PATH, "w", encoding="utf-8") as flags_file:
        json.dump({
            "USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 100,
            "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
            "KILL_SWITCH": False, "DEGRADATION": {"enabled": True},
            "HIPPOGRAPH_FEEDBACK_ENABLED": True,
            "RANKING_NUDGE_EXPERIMENT_ENABLED": True,
            "RANKING_NUDGE_EXPERIMENT_ID": "ranking_nudge_v1",
            "RANKING_NUDGE_CANARY_FRACTION": 1.0,
        }, flags_file)
    laptop_nodes = search_nodes("Laptops", limit=1)
    assert laptop_nodes, "pinned taxonomy does not contain the laptop fixture node"
    laptop_node = laptop_nodes[0]
    sold_node_added = False
    with db_session() as db:
        apply_taxonomy_migration(db)
        try:
            ensure_experiment_tables(db)
        except RuntimeError:
            apply_experiment_migrations(db)
        db.execute(text("INSERT OR REPLACE INTO products (id,sku,name,price_cents,currency,specs,active) "
                        "VALUES ('RNW-1','RNW-1','RN Laptop',119900,'AUD','{}',1)"))
        db.execute(text("INSERT OR REPLACE INTO inventory (id,product_id,stock,warehouse) "
                        "VALUES ('inv-rnw1','RNW-1',5,'default')"))
        existing_sold = db.execute(
            text(
                "SELECT 1 FROM sold_taxonomy "
                "WHERE tenant_id='default' AND node_handle=:node_handle"
            ),
            {"node_handle": laptop_node.handle},
        ).fetchone()
        assert upsert_classification(
            db,
            sku="RNW-1",
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
        _delete_ranking_experiment(db)
        experiment_id = create_sealed_experiment(
            db, name="ranking_nudge_v1", target_metric="conversion"
        )
        assert experiment_id, "migration-owned sealed experiment fixture was not created"
        db.commit()
    # Recall the first V2-served SKU; the compatibility route no longer uses
    # RecommendationService, so characterize the implementation that serves it.
    monkeypatch.setattr(
        "src.app.services.hippograph_feedback.build_hippograph_insights",
        lambda *a, **k: [{
            "id": str((k.get("seed_skus") or [""])[0]),
            "kind": "product", "label": "V2 candidate",
            "score": 9.0, "reward_weight": 5.0,
        }],
    )
    yield monkeypatch
    if orig_flags is not None:
        with open(_FLAGS_PATH, "w", encoding="utf-8") as f:
            f.write(orig_flags)
    with db_session() as db:
        db.execute(text("DELETE FROM inventory WHERE product_id='RNW-1'"))
        db.execute(text("DELETE FROM products WHERE id='RNW-1'"))
        db.execute(
            text(
                "DELETE FROM product_classification "
                "WHERE tenant_id='default' AND sku='RNW-1'"
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
        _delete_ranking_experiment(db)
        db.commit()


def _suggest(uid):
    # Use the fixture-owned catalog identity. A migration-only hosted database
    # intentionally has no tenant taxonomy/classification rows, so a broad
    # natural-language phrase would test onboarding state rather than nudge
    # projection.
    r = client.get(
        "/api/v1/recommend/suggest",
        params={"uid": uid, "query": "RN Laptop", "budget_max": 1500},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_treatment_user_is_nudged(nudge_stack):
    # canary_assignment resolves assign_variant from the experiment_ops namespace (imported there);
    # with a 100% canary fraction every subject is eligible, so the forced arm applies.
    nudge_stack.setattr("src.app.services.experiment_ops.assign_variant", lambda **k: "treatment")
    body = _suggest("rnw-treat")
    assert body.get("products"), json.dumps(body, indent=2)
    exp = body.get("ranking_experiment")
    assert exp, body
    assert exp["variant"] == "treatment" and exp["live"] is True
    assert exp["nudged"] >= 1, body  # the recalled product was boosted


def test_control_user_is_untouched(nudge_stack):
    nudge_stack.setattr("src.app.services.experiment_ops.assign_variant", lambda **k: "control")
    body = _suggest("rnw-ctrl")
    exp = body.get("ranking_experiment")
    assert exp, body
    assert exp["variant"] == "control"
    assert exp["nudged"] == 0  # control is never nudged
