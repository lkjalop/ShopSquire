import json

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.services.query_classifier import classify_turn_intent
from tests.utils import default_headers


def _client() -> TestClient:
    return TestClient(create_app(), headers=default_headers())


def test_classify_turn_intent_treats_cracked_query_as_support_claim():
    assert classify_turn_intent(
        query="i cracked my macbook! who do i talk to?",
        nlp={},
        followup_explain=False,
        explicit_constraint_update=False,
    ) == "SUPPORT_CLAIM"


def test_recommend_routes_damage_score_cv_triage_to_support_panel():
    r = _client().get(
        "/api/v1/recommend/suggest",
        params={
            "uid": "u-support-claim-2",
            "query": "show me this device",
            "image_labels": "macbook",
            "image_intent": "cv_triage",
            "image_cv_signals": json.dumps({"intent_cv_triage": True, "damage_score": 0.72}),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body.get("results") or []) == 0, body
    panel = body.get("right_panel") or {}
    assert panel.get("mode") == "support", body
    assert "damaged device" in str(body.get("assistant_message") or "").lower(), body
