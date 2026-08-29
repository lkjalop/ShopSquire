"""Held-out replay contract for the four URL/switch regressions."""
from __future__ import annotations

from src.app.services.buyer_evidence_source_resolution import (
    extract_submitted_source_url,
    resolve_buyer_evidence_source,
)
from src.app.services.connectors.steam_requirements import get_game_requirements
from src.app.services.official_source_governance import load_official_source_manifest
from src.app.services.recommendation_core.literal_workload_identity import (
    deterministic_named_workload_switch,
    literal_game_identity_candidate,
)
from src.app.services.subject_switch_boundary import clear_subject_scoped_state


def _sources():
    return load_official_source_manifest()["sources"]


def test_replay_first_turn_emulate3d_url_is_isolated_and_receiptable():
    utterance = (
        "I need a digital twin computer. Link: "
        "https://store.sim3d.com/demo3d_2025/system_requirements?token=discard"
    )
    url = extract_submitted_source_url(utterance)
    resolution = resolve_buyer_evidence_source(source_url=url, sources=_sources())
    assert resolution.status == "resolved"
    assert resolution.selected_source_id == "rockwell_emulate3d_official_requirements"
    assert resolution.submitted_url == "https://store.sim3d.com/demo3d_2025/system_requirements"
    assert "discard" not in str(resolution.model_dump(mode="json"))


def test_replay_digital_twin_to_heroes_clears_subject_authority_retains_budget():
    utterance = "I want a laptop to play the new remastered Heroes of Might and Magic 3."
    assert deterministic_named_workload_switch(utterance) is True
    state = {
        "budget_max": 3000, "currency": "AUD",
        "canonical_case": {"objective": "digital twin"},
        "external_research_consent": True,
        "research_state": {"source": "rockwell"},
        "workload_evidence": [{"name": "Emulate3D"}],
    }
    receipt = clear_subject_scoped_state(state)
    assert state == {"budget_max": 3000, "currency": "AUD"}
    assert receipt["research_authority"] == "required"
    identities = literal_game_identity_candidate(utterance)
    assert identities == (("game", "new remastered Heroes of Might and Magic 3"),)


def test_replay_heroes_to_bg3_resolves_complete_canonical_identity():
    utterance = "What about Baldur's Gate 3?"
    assert deterministic_named_workload_switch(utterance) is True
    candidates = literal_game_identity_candidate(utterance)
    identity = get_game_requirements(candidates[0][1] if candidates else "")
    assert identity is not None
    assert identity["title"] == "Baldur's Gate 3"
    assert identity["publisher"] == "Larian Studios"
    assert identity["appid"] == 1086940
    assert identity["release_state"] == "released"
    assert identity["requirements_completeness"] == "minimum_and_recommended"


def test_replay_unenrolled_larian_url_is_zero_fetch_rejection_candidate():
    resolution = resolve_buyer_evidence_source(
        source_url="https://larian.com/support/faqs/bg3?credential=discard",
        sources=_sources(),
    )
    assert resolution.status == "not_enrolled"
    assert resolution.external_calls == 0
    assert resolution.canonical_fetch_eligible is False
    assert "discard" not in str(resolution.model_dump(mode="json"))
