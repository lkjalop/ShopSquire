import json

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.routers import escalation_room
from tests.utils import default_headers


def test_admin_incident_sse_requires_staff_authentication():
    client = TestClient(create_app())
    response = client.get("/api/v1/admin/incidents/inc-secret/room/stream")
    assert response.status_code in {401, 403}


def test_admin_message_ignores_client_supplied_staff_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(escalation_room, "_CHAT_DIR", tmp_path)
    escalation_room.INCIDENT_CONVERSATION_RUNTIME.local_presence.clear()
    client = TestClient(create_app(), headers=default_headers())

    response = client.post(
        "/api/v1/admin/incidents/inc-identity/room/message",
        json={"message": "I have joined.", "role": "buyer"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["role"] != "buyer"
    assert body["actor"]["identity_source"] == "authenticated_server_role"
    assert body["message_id"].startswith("ice-")
    assert body["delivery_status"] == "delivered"


def test_resolved_incident_rejects_further_messages(monkeypatch):
    monkeypatch.setattr(escalation_room, "_incident_room_is_closed", lambda _incident_id: True)
    client = TestClient(create_app(), headers=default_headers())

    response = client.post(
        "/api/v1/admin/incidents/inc-resolved/room/message",
        json={"message": "This must not be posted."},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "incident_room_closed"


def test_read_acknowledgement_requires_target_message_id():
    client = TestClient(create_app(), headers=default_headers())
    response = client.post(
        "/api/v1/admin/incidents/inc-read/room/message",
        json={"event_type": "read"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "message_id_required"


def test_incident_token_cannot_cross_incident_boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(escalation_room, "_TOKENS_DIR", tmp_path)
    first = escalation_room._issue_tokens("inc-first")
    escalation_room._issue_tokens("inc-second")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/incidents/inc-second/room/message",
        headers={"x-incident-token": first["buyer_token"]},
        json={"message": "Cross-incident access must fail."},
    )

    assert response.status_code == 401


def test_html_is_persisted_as_plain_message_data(monkeypatch, tmp_path):
    monkeypatch.setattr(escalation_room, "_CHAT_DIR", tmp_path)
    record = escalation_room._append_chat(
        "inc-xss",
        "buyer",
        "<script>alert(1)</script>",
    )
    assert record["message"] == "<script>alert(1)</script>"
    assert record["event_type"] == "message"


def test_human_substitute_message_is_advisory_and_requires_buyer_confirmation(monkeypatch, tmp_path):
    monkeypatch.setattr(escalation_room, "_CHAT_DIR", tmp_path)
    escalation_room.INCIDENT_CONVERSATION_RUNTIME.local_presence.clear()
    client = TestClient(create_app(), headers=default_headers())
    response = client.post(
        "/api/v1/admin/incidents/inc-substitute/room/message",
        json={"message": "Supplier offered MODEL-B.", "message_kind": "proposed_substitute"},
    )
    assert response.status_code == 200
    records = [json.loads(line) for line in (tmp_path / "inc-substitute.ndjson").read_text().splitlines()]
    proposal = records[-1]
    assert proposal["event_type"] == "proposed_substitute"
    assert proposal["meta"]["commercial_authority"] == "none"
    assert proposal["meta"]["buyer_confirmation_required"] is True
