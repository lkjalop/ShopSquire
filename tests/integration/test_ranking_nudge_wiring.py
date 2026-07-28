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
from src.app.services import experiments as ex
from tests.utils import default_headers

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
client = TestClient(app, headers=default_headers())


@pytest.fixture()
def nudge_stack(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_MODE", "skip")
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
    with db_session() as db:
        db.execute(text("INSERT OR REPLACE INTO products (id,sku,name,price_cents,currency,specs,active) "
                        "VALUES ('RNW-1','RNW-1','RN Laptop',119900,'USD','{}',1)"))
        db.execute(text("INSERT OR REPLACE INTO inventory (id,product_id,stock,warehouse) "
                        "VALUES ('inv-rnw1','RNW-1',5,'default')"))
        ex.create_experiment(db, name="ranking_nudge_v1", target_metric="conversion", status="live")
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
        db.execute(text("DELETE FROM experiment_run WHERE name='ranking_nudge_v1'"))
        db.commit()


def _suggest(uid):
    r = client.get("/api/v1/recommend/suggest", params={"uid": uid, "query": "laptop for work under 1500"})
    assert r.status_code == 200, r.text
    return r.json()


def test_treatment_user_is_nudged(nudge_stack):
    # canary_assignment resolves assign_variant from the experiment_ops namespace (imported there);
    # with a 100% canary fraction every subject is eligible, so the forced arm applies.
    nudge_stack.setattr("src.app.services.experiment_ops.assign_variant", lambda **k: "treatment")
    body = _suggest("rnw-treat")
    exp = body.get("ranking_experiment")
    assert exp and exp["variant"] == "treatment" and exp["live"] is True
    assert exp["nudged"] >= 1, body  # the recalled product was boosted


def test_control_user_is_untouched(nudge_stack):
    nudge_stack.setattr("src.app.services.experiment_ops.assign_variant", lambda **k: "control")
    body = _suggest("rnw-ctrl")
    exp = body.get("ranking_experiment")
    assert exp and exp["variant"] == "control"
    assert exp["nudged"] == 0  # control is never nudged
