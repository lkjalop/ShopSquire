"""Supplier communication-channel router — who acts per channel (agent-draft / human-only / integration)."""
from src.app.services.fulfillment.supplier_channel import resolve_channel, CHANNEL_EMAIL


def test_email_lets_an_agent_draft_but_not_send():
    p = resolve_channel("email")
    assert p.agent_may_draft is True and p.requires_human is False and p.integration_kind is None


def test_phone_is_human_only_never_an_agent_voice_call():
    p = resolve_channel("phone")
    assert p.requires_human is True and p.agent_may_draft is False
    assert "human" in p.rationale.lower() and "scam" in p.rationale.lower()


def test_portal_is_human_only():
    p = resolve_channel("portal")
    assert p.requires_human is True and p.agent_may_draft is False and p.integration_kind is None


def test_edi_cxml_api_route_to_a_system_integration_not_email():
    for ch in ("edi", "cxml", "api"):
        p = resolve_channel(ch)
        assert p.integration_kind == ch and p.agent_may_draft is False and p.requires_human is False


def test_unknown_or_missing_channel_defaults_to_email_safely():
    for ch in (None, "", "carrier-pigeon"):
        p = resolve_channel(ch)
        assert p.channel == CHANNEL_EMAIL and p.agent_may_draft is True
