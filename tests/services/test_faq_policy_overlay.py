"""Tests for FAQ policy overlay and export_policy_rules_json()."""
from __future__ import annotations

from src.app.services.faq_bank import FAQ_BANK, export_policy_rules_json, match_faq


def test_policy_fields_injected_on_return_entry():
    hits = [e for e in FAQ_BANK if "return policy" in str(e.get("q", "")).lower()]
    assert hits, "Return policy FAQ entry not found"
    e = hits[0]
    assert e.get("policy_rule") == "return_policy_v1"
    assert e.get("confidence_threshold") == 0.80
    assert e.get("fraud_gate") is True
    assert e.get("autonomy_tier") == "auto"


def test_policy_fields_injected_on_liquid_damage():
    hits = [e for e in FAQ_BANK if "liquid damage" in str(e.get("q", "")).lower()]
    assert hits, "Liquid damage FAQ entry not found"
    e = hits[0]
    assert e.get("policy_rule") == "liquid_damage_v1"
    assert e.get("autonomy_tier") == "escalate"
    assert e.get("fraud_gate") is True


def test_policy_fields_injected_on_bsod():
    hits = [e for e in FAQ_BANK if "blue screen" in str(e.get("q", "")).lower()]
    assert hits, "BSOD FAQ entry not found"
    e = hits[0]
    assert e.get("policy_rule") == "hardware_fault_v1"
    assert "stop_code" in (e.get("nqe_required_fields") or [])


def test_entries_without_policy_unaffected():
    """FAQ entries not matching any policy fragment should have no policy_rule."""
    hits = [e for e in FAQ_BANK if "gift card" in str(e.get("q", "")).lower()]
    assert hits
    e = hits[0]
    assert "policy_rule" not in e


def test_export_policy_rules_json_returns_dict():
    rules = export_policy_rules_json()
    assert isinstance(rules, dict)
    assert len(rules) >= 15, f"Expected at least 15 policy rules, got {len(rules)}"


def test_export_policy_rules_json_structure():
    rules = export_policy_rules_json()
    for q, rule in rules.items():
        assert "policy_rule" in rule
        assert "confidence_threshold" in rule
        assert "autonomy_tier" in rule
        assert isinstance(rule["fraud_gate"], bool)


def test_match_faq_still_works_after_overlay():
    """match_faq() must still return correct matches after policy enrichment."""
    entry, score = match_faq("I want to return my item")
    assert entry is not None
    assert score > 0
    # Should match a return-related entry
    assert any(tag in (entry.get("tags") or []) for tag in ("return", "exchange"))
