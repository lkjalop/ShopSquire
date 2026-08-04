"""support_playbooks profile slot — the clarify support builder reads vertical copy from the
profile; core carries a vertical-neutral default so a slot-less profile still answers honestly."""
from __future__ import annotations

from src.app.services import recommend_clarify_payloads as rcp

_COMMON = dict(
    constraints={"issue_type": "cracked_screen"}, followup_contract=None, intent_execution_plan=None,
    policy_version="v1", image_reupload_reasons=None, question_plan={}, view_hint={}, strategy_corr={},
    llm_model="m", model_tier="t", complexity_signals={}, nqe_selection_applied=False, turn_type="x",
    referents=[], memory_confidence=0.5,
)


def test_electronics_slot_drives_device_copy(monkeypatch):
    # active profile = electronics (its JSON carries the device-specific slot)
    p = rcp.build_support_clarify_payload(
        warranty={"status": "found", "message": "Covered", "order_ref": "ORD-9"}, **_COMMON)
    assert "damaged device" in p["assistant_message"]
    assert [c["title"] for c in p["right_panel"]["support_cards"]] == ["Warranty/Coverage", "Repair / Return Path"]
    assert "CV_Triage_Agent" in p["right_panel"]["parallel_agents"]
    # live warranty result binds onto the status_from='warranty' card
    card0 = p["right_panel"]["support_cards"][0]
    assert card0["status"] == "found" and card0["order_ref"] == "ORD-9"
    assert "status_from" not in card0  # the binding key is stripped from output


def test_neutral_default_when_slot_absent(monkeypatch):
    monkeypatch.setattr(rcp, "_support_playbook", lambda: rcp._DEFAULT_SUPPORT_PLAYBOOK)
    p = rcp.build_support_clarify_payload(warranty={}, **_COMMON)
    # neutral copy: no "device" vocabulary, honest generic support language
    assert "device" not in p["assistant_message"].lower()
    assert "returns" in p["assistant_message"].lower() or "replacements" in p["assistant_message"].lower()
    assert p["right_panel"]["support_cards"][0]["status"] == "unknown"  # no warranty -> unknown
