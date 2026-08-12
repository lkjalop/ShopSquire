from src.app.services.incident_conversation_identity import build_conversation_event, server_actor_identity


def test_staff_subject_produces_distinct_server_owned_actor_ids():
    first = server_actor_identity("merchant", subject="alice@example.com")
    second = server_actor_identity("merchant", subject="bob@example.com")
    assert first["actor_id"] != second["actor_id"]
    assert first["identity_source"] == "authenticated_server_role"


def test_staff_identity_is_server_derived(monkeypatch):
    monkeypatch.setenv("INCIDENT_STAFF_MERCHANT_DISPLAY_NAME", "Alex Chen")
    monkeypatch.setenv("INCIDENT_STAFF_MERCHANT_TITLE", "Procurement specialist")

    actor = server_actor_identity("merchant")

    assert actor == {
        "actor_id": "staff:merchant",
        "actor_type": "human_staff",
        "display_name": "Alex Chen",
        "title": "Procurement specialist",
        "avatar_url": None,
        "identity_source": "authenticated_server_role",
    }


def test_conversation_event_has_stable_buyer_visible_delivery_shape():
    event = build_conversation_event(
        incident_id="inc-1",
        role="merchant",
        message="I can help with the supplier options.",
    )

    assert event["id"] == event["event_id"]
    assert event["actor"]["actor_type"] == "human_staff"
    assert event["delivery_status"] == "delivered"
    assert event["meta"]["actor_identity"] == event["actor"]
