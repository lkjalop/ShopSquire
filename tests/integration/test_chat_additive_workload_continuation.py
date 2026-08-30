from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app


_SEEN = []


async def _fake_unresolved_recommend(request, params, **kwargs):
    _SEEN.append(dict(params or {}))
    return 200, {
        "results": [],
        "assistant_message": "Research is required before product qualification.",
        "decision_trace_id": f"trace-additive-{len(_SEEN)}",
        "turn_intent": "SEARCH",
        "semantic_resolution": {
            "catalog_authority": "blocked",
            "reasons": ["requirements_unresolved"],
        },
        "workload_authorization": {
            "status": "blocked",
            "reason": "requirements_unresolved",
            "evidence": [],
        },
        "next_questions": [],
    }


def test_bg3_budget_then_emulate3d_as_well_retains_shared_budget_and_combines_case(monkeypatch):
    from src.app.routers import chat as chat_router

    _SEEN.clear()
    monkeypatch.setattr(
        chat_router, "_call_recommend_in_process", _fake_unresolved_recommend,
    )
    app = create_app()
    # These case-ledger tables are migration-owned in production and are not
    # part of the minimal SQLite metadata used by focused integration tests.
    with app.state.engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS conversation_case_state (
                id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
                session_epoch TEXT NOT NULL, subject_ref TEXT NOT NULL,
                version INTEGER NOT NULL, state_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(tenant_id, case_id, session_epoch)
            )
        """))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS conversation_case_amendment (
                id TEXT PRIMARY KEY, case_state_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL, case_id TEXT NOT NULL,
                session_epoch TEXT NOT NULL, source_message_id TEXT NOT NULL,
                trace_id TEXT, dialogue_act TEXT NOT NULL, field_name TEXT,
                old_value_json TEXT, proposed_value_json TEXT,
                confidence REAL NOT NULL, risk TEXT NOT NULL,
                requires_confirmation INTEGER NOT NULL, status TEXT NOT NULL,
                reason TEXT NOT NULL, provenance_json TEXT NOT NULL,
                supersedes_id TEXT, observed_at TEXT NOT NULL,
                effective_at TEXT, created_at TEXT NOT NULL
            )
        """))
    client = TestClient(app)
    headers = {"x-api-key": "local-merchant-key"}
    isolation = uuid4().hex
    uid = f"u-chat-additive-{isolation}"
    session_id = f"s-chat-additive-{isolation}"
    first = client.post(
        "/api/v1/chat/query",
        json={
            "uid": uid,
            "session_id": session_id,
            "query": "Is AUD 3,200 excessive for Baldur’s Gate 3",
        },
        headers=headers,
    )
    assert first.status_code == 200
    first_body = first.json()
    assert first_body["confirmed_slots"]["budget_max"] == 3200
    assert first_body["ambiguity_exploration"]["status"] == "context_only"
    assert first_body["ambiguity_exploration"]["identity_candidates"][0]["canonical_title"] == "Baldur's Gate 3"
    case_id = first_body["shopping_case_id"]

    second = client.post(
        "/api/v1/chat/query",
        json={
            "uid": uid,
            "session_id": session_id,
            "shopping_case_id": case_id,
            "confirmed_slots": first_body["confirmed_slots"],
            "query": "It must run Rockwell Emulate3D locally as well",
        },
        headers=headers,
    )
    assert second.status_code == 200
    body = second.json()
    receipt = body["case_additive_workload"]
    assert receipt["status"] == "retained_and_added"
    assert receipt["source_candidate_ids"] == [
        "rockwell_emulate3d_official_requirements"
    ]
    assert "Baldur’s Gate 3" in receipt["combined_purpose"]
    assert "Rockwell Emulate3D" in receipt["combined_purpose"]
    assert body["confirmed_slots"]["budget_max"] == 3200
    assert body["products"] == []
    assert body["ambiguity_exploration"]["status"] == "provisional"
    assert body["ambiguity_exploration"]["evidence"] == "partial_identity_material_gap"
    assert "retained your AUD 3,200 budget" in body["assistant_message"]
    assert "Rockwell Emulate3D" in body["assistant_message"]
    assert _SEEN[-1]["confirmed_slots"]["budget_max"] == 3200
    assert _SEEN[-1]["query"] == receipt["combined_purpose"]
