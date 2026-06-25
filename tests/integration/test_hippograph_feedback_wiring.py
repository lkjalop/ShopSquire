"""Flag-ON proof that hippograph feedback reaches BOTH the response and the NQE agent.

GPT-5.5 found NQEInput.hippograph_context was [] even when hippograph_insights appeared in the
response — i.e. feedback was annotation, not agent injection. This locks the fix: with the flag on,
the recall reaches payload.hippograph_insights AND the NQE agent's NQEInput.hippograph_context.
The recall builder is patched to a sentinel to isolate the WIRING from graph contents.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import app
from src.app.models.db import db_session
from src.app.services.recommendations import RecommendationService
from tests.test_recommend import _write_flags
from tests.utils import default_headers

_FLAGS_PATH = os.path.join("config", "feature_flags.json")
_SENTINEL = [{"id": "GAM-HOT", "kind": "product", "label": "Hot Pick", "score": 9.9, "reward_weight": 5.0}]

client = TestClient(app, headers=default_headers())


@pytest.fixture()
def feedback_on(monkeypatch):
    monkeypatch.setenv("RECOMMEND_NARRATION_MODE", "skip")
    orig = RecommendationService.retrieve_candidates
    RecommendationService.retrieve_candidates = lambda self, q, limit=10: []
    orig_flags = open(_FLAGS_PATH, encoding="utf-8").read() if os.path.isfile(_FLAGS_PATH) else None
    _write_flags({
        "USE_AGENT_CAPABILITIES": True, "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False, "DEGRADATION": {"enabled": True},
        "HIPPOGRAPH_FEEDBACK_ENABLED": True,
    })
    with db_session() as db:
        db.execute(text("INSERT OR REPLACE INTO products (id,sku,name,price_cents,currency,specs,active) "
                        "VALUES ('HGW-1','HGW-1','HG Laptop',119900,'USD','{}',1)"))
        db.execute(text("INSERT OR REPLACE INTO inventory (id,product_id,stock,warehouse) "
                        "VALUES ('inv-hgw1','HGW-1',5,'default')"))
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
        db.commit()


def test_feedback_reaches_response_and_nqe(feedback_on, monkeypatch):
    captured = {}
    from src.app.flows.nqe import NextQuestionEngine
    orig_propose = NextQuestionEngine.propose

    def _cap(self, inp):
        captured["ctx"] = list(getattr(inp, "hippograph_context", None) or [])
        return orig_propose(self, inp)

    monkeypatch.setattr(NextQuestionEngine, "propose", _cap)
    r = client.get("/api/v1/recommend/suggest", params={"uid": "hgw-user", "query": "laptop for work under 1500"})
    assert r.status_code == 200, r.text
    body = r.json()
    # 1) reaches the response
    assert body.get("hippograph_insights") == _SENTINEL
    # 2) reaches the NQE agent (the exact gap GPT flagged: NQEInput.hippograph_context was []).
    assert captured.get("ctx") == _SENTINEL, "NQEInput.hippograph_context must carry the recall"
