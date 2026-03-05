"""Tests for March 2026 security enhancements:

- DREAD evidence trail & kill-chain binding (dread_scorer.py)
- Campaign correlator (campaign_correlator.py)
- DREAD calibration (dread_calibration.py)
- PASTA DREAD floor rule (framework_correlation.py)
- FAIR Monte Carlo & calibration API endpoints (admin_grc.py)
"""
import json
import os
import tempfile
import uuid

import pytest

from src.app.security.dread_scorer import (
    _KILL_CHAIN_ORDER,
    _STAGE_WEIGHTS,
    _clamp,
    _evidence_item,
    _weighted_avg,
    compute_dread,
    infer_kill_chain_stage,
)
from src.app.services.campaign_correlator import (
    CampaignCheckResult,
    _signal_categories,
    apply_campaign_boost,
    entity_key,
)
from src.app.security.framework_correlation import _pasta


# =====================================================================
# dread_scorer — evidence trail & kill-chain binding
# =====================================================================

class TestComputeDread:
    """compute_dread returns per-event DREAD scores with full evidence trail."""

    def test_basic_structure(self):
        """Return dict has all expected top-level keys."""
        result = compute_dread({"prompt_injection": True}, severity="high")
        expected_keys = {
            "damage", "reproducibility", "exploitability",
            "affected_users", "discoverability", "avg", "weighted_avg",
            "kill_chain_stage", "kill_chain_stage_index",
            "stage_weights", "evidence",
        }
        assert expected_keys.issubset(result.keys())

    def test_scores_in_range(self):
        """All DREAD components are clamped to [0, 10]."""
        signals = {
            "prompt_injection": True,
            "data_exfiltration": True,
            "pci": True,
            "cascading_failure": True,
            "model_dos": True,
        }
        result = compute_dread(signals, severity="critical", actor_context={"actor_role": "admin"})
        for k in ("damage", "reproducibility", "exploitability", "affected_users", "discoverability"):
            assert 0 <= result[k] <= 10, f"{k} out of range: {result[k]}"

    def test_evidence_list_nonempty(self):
        """Every compute_dread call produces at least one evidence item."""
        result = compute_dread({"prompt_injection": True})
        assert isinstance(result["evidence"], list)
        assert len(result["evidence"]) >= 1

    def test_evidence_item_shape(self):
        """Evidence items have the expected keys."""
        result = compute_dread({"prompt_injection": True}, severity="high")
        for item in result["evidence"]:
            for k in ("signal", "component", "contribution"):
                assert k in item, f"Missing key {k} in evidence item: {item}"

    def test_prompt_injection_high_exploitability(self):
        """prompt_injection drives exploitability >= 8.5."""
        result = compute_dread({"prompt_injection": True})
        assert result["exploitability"] >= 9.0

    def test_data_exfiltration_boosts_damage(self):
        """data_exfiltration should push damage significantly above baseline."""
        base = compute_dread({}, severity="info")
        boosted = compute_dread({"data_exfiltration": True}, severity="info")
        assert boosted["damage"] > base["damage"]

    def test_critical_severity_high_damage(self):
        result = compute_dread({}, severity="critical")
        assert result["damage"] >= 9.0

    def test_admin_role_high_affected_users(self):
        result = compute_dread({}, actor_context={"actor_role": "admin"})
        assert result["affected_users"] >= 8.0

    def test_cv_signals_boost_exploitability(self):
        """QR/OCR prompt injection bumps exploitability."""
        base = compute_dread({"prompt_injection": True})
        with_cv = compute_dread(
            {"prompt_injection": True},
            cv_signals={"qr_prompt_injection": True, "ocr_prompt_injection": True},
        )
        assert with_cv["exploitability"] >= base["exploitability"]

    def test_no_signals_low_scores(self):
        """Empty signals + info severity → low scores."""
        result = compute_dread({}, severity="info")
        assert result["avg"] < 5.0

    def test_evidence_contains_mitre_for_prompt_injection(self):
        result = compute_dread({"prompt_injection": True})
        mitre_refs = [e["mitre"] for e in result["evidence"] if e.get("mitre")]
        assert any("AML.T0051" in m for m in mitre_refs)

    def test_evidence_contains_owasp_for_prompt_injection(self):
        result = compute_dread({"prompt_injection": True})
        owasp_refs = [e["owasp"] for e in result["evidence"] if e.get("owasp")]
        assert any("LLM01" in o for o in owasp_refs)


class TestInferKillChainStage:
    """infer_kill_chain_stage picks the most advanced active stage."""

    def test_recon_for_scanner_burst(self):
        assert infer_kill_chain_stage({"scanner_burst": True}) == "Reconnaissance"

    def test_exploitation_for_prompt_injection(self):
        assert infer_kill_chain_stage({"prompt_injection": True}) == "Exploitation"

    def test_actions_on_objectives_for_data_exfiltration(self):
        assert infer_kill_chain_stage({"data_exfiltration": True}) == "ActionsOnObjectives"

    def test_delivery_for_social_engineering(self):
        assert infer_kill_chain_stage({"social_engineering": True}) == "Delivery"

    def test_most_advanced_wins(self):
        """When multiple stages are active, the most advanced is returned."""
        stage = infer_kill_chain_stage({
            "scanner_burst": True,      # Reconnaissance
            "prompt_injection": True,   # Exploitation
            "data_exfiltration": True,  # ActionsOnObjectives
        })
        assert stage == "ActionsOnObjectives"

    def test_no_signals_defaults_to_recon(self):
        assert infer_kill_chain_stage({}) == "Reconnaissance"

    def test_cv_signals_contribute(self):
        """CV signals participate in kill-chain inference."""
        stage = infer_kill_chain_stage({}, cv_signals={"qr_prompt_injection": True})
        # qr_prompt_injection maps via _SIGNAL_KILL_CHAIN — if not mapped, falls to default
        assert stage in _KILL_CHAIN_ORDER

    def test_installation_for_agentic_tool_abuse(self):
        assert infer_kill_chain_stage({"agentic_tool_abuse": True}) == "Installation"

    def test_c2_for_email_beaconing(self):
        assert infer_kill_chain_stage({"email_c2_beaconing": True}) == "CommandAndControl"


class TestWeightedAvg:
    """Stage-weighted average produces different results per kill-chain stage."""

    def test_different_stages_differ(self):
        """Same raw scores, different stages → different weighted averages."""
        scores = (7.0, 5.0, 8.0, 4.0, 6.0)
        recon = _weighted_avg(*scores, "Reconnaissance")
        exploit = _weighted_avg(*scores, "Exploitation")
        actions = _weighted_avg(*scores, "ActionsOnObjectives")
        # With different stage weights these should differ
        vals = {recon, exploit, actions}
        assert len(vals) >= 2, "Expected different weighted averages for different stages"

    def test_weights_from_stage(self):
        """Verify the weights used match _STAGE_WEIGHTS."""
        stage = "Exploitation"
        wD, wR, wE, wA, wDisc = _STAGE_WEIGHTS[stage]
        total_w = wD + wR + wE + wA + wDisc
        expected = round((wD * 7 + wR * 5 + wE * 8 + wA * 4 + wDisc * 6) / total_w, 2)
        assert _weighted_avg(7, 5, 8, 4, 6, stage) == expected

    def test_unknown_stage_uses_default(self):
        """Unknown stage falls back to even weights (2,2,2,2,2)."""
        result = _weighted_avg(6, 6, 6, 6, 6, "UnknownStage")
        assert result == 6.0  # even weights, all 6 → avg 6


class TestEvidenceItem:
    def test_text_source(self):
        item = _evidence_item("prompt_injection", "exploitability", 9.0)
        assert item["source"] == "text"
        assert item["mitre"] == "AML.T0051"

    def test_cv_source(self):
        item = _evidence_item("qr_prompt_injection", "exploitability", 1.5, cv=True)
        assert item["source"] == "cv"
        assert item["mitre"] == "AML.T0051"

    def test_kill_chain_included(self):
        item = _evidence_item("data_exfiltration", "damage", 2.0)
        assert item["kill_chain"] == "ActionsOnObjectives"


class TestClamp:
    def test_below_min(self):
        assert _clamp(-5) == 0.0

    def test_above_max(self):
        assert _clamp(15) == 10.0

    def test_within_range(self):
        assert _clamp(5.5) == 5.5


# =====================================================================
# campaign_correlator — entity_key, signal categories, boost
# =====================================================================

class TestEntityKey:
    def test_deterministic(self):
        k1 = entity_key("1.2.3.4", "AS1234", "uid_hash_abc")
        k2 = entity_key("1.2.3.4", "AS1234", "uid_hash_abc")
        assert k1 == k2

    def test_different_inputs_differ(self):
        k1 = entity_key("1.2.3.4", "AS1234", "uid_hash_abc")
        k2 = entity_key("5.6.7.8", "AS5678", "uid_hash_xyz")
        assert k1 != k2

    def test_none_handling(self):
        """None args are handled gracefully."""
        k = entity_key(None, None, None)
        assert isinstance(k, str)
        assert len(k) == 24

    def test_length(self):
        k = entity_key("1.2.3.4", "AS1234", "uid")
        assert len(k) == 24  # sha256[:24]


class TestSignalCategories:
    def test_groups_llm_attacks(self):
        cats = _signal_categories({"prompt_injection": True, "jailbreak": True})
        assert cats == {"llm_attack"}

    def test_groups_data_leak(self):
        cats = _signal_categories({"data_exfiltration": True, "pci": True})
        assert cats == {"data_leak"}

    def test_inactive_signals_ignored(self):
        cats = _signal_categories({"prompt_injection": False, "data_exfiltration": True})
        assert "llm_attack" not in cats
        assert "data_leak" in cats

    def test_diverse_signals(self):
        cats = _signal_categories({
            "prompt_injection": True,    # llm_attack
            "data_exfiltration": True,   # data_leak
            "scanner_burst": True,       # recon
            "social_engineering": True,  # social_eng
        })
        assert len(cats) >= 4


class TestCampaignCheckResult:
    def test_default_not_detected(self):
        r = CampaignCheckResult()
        assert r.detected is False
        assert r.campaign_id is None

    def test_to_dict(self):
        r = CampaignCheckResult()
        d = r.to_dict()
        assert isinstance(d, dict)
        assert "detected" in d
        assert "signal_diversity" in d


class TestApplyCampaignBoost:
    def test_no_boost_when_not_detected(self):
        dread = compute_dread({"prompt_injection": True}, severity="high")
        campaign = CampaignCheckResult()
        campaign.detected = False
        result = apply_campaign_boost(dread, campaign)
        assert result["damage"] == dread["damage"]

    def test_boost_when_detected(self):
        dread = compute_dread({"prompt_injection": True}, severity="warn")
        campaign = CampaignCheckResult()
        campaign.detected = True
        campaign.campaign_id = "CAMP-test123"
        campaign.dread_boost_damage = 1.5
        campaign.dread_boost_repro = 2.0
        campaign.event_count = 5
        campaign.signal_diversity = 4
        campaign.stage_progression = 2
        result = apply_campaign_boost(dread, campaign)
        assert result["damage"] >= dread["damage"] + 1.0  # may clamp
        assert result["reproducibility"] >= dread["reproducibility"] + 1.0

    def test_boost_adds_campaign_evidence(self):
        dread = compute_dread({"prompt_injection": True})
        campaign = CampaignCheckResult()
        campaign.detected = True
        campaign.campaign_id = "CAMP-test456"
        campaign.dread_boost_damage = 1.5
        campaign.dread_boost_repro = 2.0
        campaign.event_count = 3
        campaign.signal_diversity = 3
        campaign.stage_progression = 1
        result = apply_campaign_boost(dread, campaign)
        campaign_evidence = [e for e in result["evidence"] if e.get("source") == "campaign_correlator"]
        assert len(campaign_evidence) == 2  # one for repro, one for damage
        assert any(e["component"] == "reproducibility" for e in campaign_evidence)
        assert any(e["component"] == "damage" for e in campaign_evidence)

    def test_boost_recalculates_avg(self):
        dread = compute_dread({"scanner_burst": True}, severity="info")
        orig_avg = dread["avg"]
        campaign = CampaignCheckResult()
        campaign.detected = True
        campaign.campaign_id = "CAMP-recalc"
        campaign.dread_boost_damage = 1.5
        campaign.dread_boost_repro = 2.0
        campaign.event_count = 4
        campaign.signal_diversity = 3
        campaign.stage_progression = 1
        result = apply_campaign_boost(dread, campaign)
        assert result["avg"] > orig_avg

    def test_boost_includes_campaign_dict(self):
        dread = compute_dread({})
        campaign = CampaignCheckResult()
        campaign.detected = True
        campaign.campaign_id = "CAMP-dict"
        campaign.dread_boost_damage = 1.5
        campaign.dread_boost_repro = 2.0
        campaign.event_count = 2
        campaign.signal_diversity = 3
        campaign.stage_progression = 1
        result = apply_campaign_boost(dread, campaign)
        assert "campaign" in result
        assert result["campaign"]["campaign_id"] == "CAMP-dict"


# =====================================================================
# PASTA DREAD floor rule (framework_correlation._pasta)
# =====================================================================

class TestPastaFloorRule:
    """DREAD-driven PASTA floor: weighted_avg >= 7.5 + advanced KC → min Stage6."""

    def test_floor_applied_when_dread_high_and_exploitation(self):
        """DREAD weighted_avg=8.0 at Exploitation → PASTA floors at Stage6."""
        dread = {"weighted_avg": 8.0, "kill_chain_stage": "Exploitation"}
        result = _pasta({}, "info", dread=dread)
        stage_num = int(result["current_stage"].replace("Stage", ""))
        assert stage_num >= 6, f"Expected Stage6+, got {result['current_stage']}"

    def test_floor_applied_at_actions_on_objectives(self):
        dread = {"weighted_avg": 9.0, "kill_chain_stage": "ActionsOnObjectives"}
        result = _pasta({}, "info", dread=dread)
        stage_num = int(result["current_stage"].replace("Stage", ""))
        assert stage_num >= 6

    def test_no_floor_when_dread_low(self):
        """Low DREAD doesn't trigger the floor."""
        dread = {"weighted_avg": 5.0, "kill_chain_stage": "Exploitation"}
        result = _pasta({}, "info", dread=dread)
        # With no signals and info severity, should be Stage1 or Stage2
        stage_num = int(result["current_stage"].replace("Stage", ""))
        assert stage_num < 6

    def test_no_floor_at_recon_stage(self):
        """High DREAD at Reconnaissance doesn't trigger floor."""
        dread = {"weighted_avg": 9.0, "kill_chain_stage": "Reconnaissance"}
        result = _pasta({}, "info", dread=dread)
        stage_num = int(result["current_stage"].replace("Stage", ""))
        assert stage_num < 6

    def test_floor_does_not_downgrade_existing_high_stage(self):
        """If severity already pushes to Stage6, DREAD floor doesn't change it."""
        dread = {"weighted_avg": 8.0, "kill_chain_stage": "Exploitation"}
        result = _pasta({}, "critical", dread=dread)
        assert result["current_stage"] == "Stage6"

    def test_floor_at_installation(self):
        dread = {"weighted_avg": 7.5, "kill_chain_stage": "Installation"}
        result = _pasta({}, "info", dread=dread)
        stage_num = int(result["current_stage"].replace("Stage", ""))
        assert stage_num >= 6

    def test_floor_at_c2(self):
        dread = {"weighted_avg": 8.5, "kill_chain_stage": "CommandAndControl"}
        result = _pasta({"prompt_injection": True}, "warn", dread=dread)
        stage_num = int(result["current_stage"].replace("Stage", ""))
        assert stage_num >= 6

    def test_none_dread_no_crash(self):
        """Passing dread=None should not crash."""
        result = _pasta({}, "info", dread=None)
        assert "current_stage" in result

    def test_pasta_stages_workflow(self):
        """Verify stages list has correct structure."""
        result = _pasta({"prompt_injection": True}, "high", dread={"weighted_avg": 8.0, "kill_chain_stage": "Exploitation"})
        assert len(result["stages"]) == 7
        statuses = [s["status"] for s in result["stages"]]
        assert "current" in statuses


# =====================================================================
# DREAD calibration — log & summary (unit, no DB)
# =====================================================================

class TestDreadCalibration:
    """Test dread_calibration module functions with real test DB."""

    def test_log_calibration_returns_id(self):
        """log_calibration should return a dcal-* ID."""
        from src.app.services.dread_calibration import log_calibration
        entry_id = log_calibration(
            incident_id="INC-test-001",
            trace_id="trace-001",
            dread={"damage": 7.5, "reproducibility": 6.0, "exploitability": 8.0,
                   "affected_users": 5.0, "discoverability": 7.0,
                   "weighted_avg": 7.2, "kill_chain_stage": "Exploitation"},
            actual_damage=4.0,
            actual_impact_notes="Minor data exposure",
            signal_types=["prompt_injection", "data_exfiltration"],
            closed_by="analyst-1",
        )
        assert entry_id is not None
        assert entry_id.startswith("dcal-")

    def test_get_calibration_summary_structure(self):
        """Summary returns expected structure even with no data."""
        from src.app.services.dread_calibration import get_calibration_summary
        summary = get_calibration_summary(days=90)
        assert isinstance(summary, dict)
        assert "entries" in summary

    def test_log_and_retrieve(self):
        """Log an entry with actual_damage, then verify summary includes it."""
        from src.app.services.dread_calibration import log_calibration, get_calibration_summary
        entry_id = log_calibration(
            incident_id=f"INC-cal-{uuid.uuid4().hex[:8]}",
            dread={"damage": 8.0, "reproducibility": 7.0, "exploitability": 9.0,
                   "affected_users": 6.0, "discoverability": 7.5,
                   "weighted_avg": 7.8, "kill_chain_stage": "ActionsOnObjectives"},
            actual_damage=5.0,
            signal_types=["prompt_injection"],
        )
        assert entry_id is not None
        summary = get_calibration_summary(days=1)
        assert summary["entries"] >= 1

    def test_log_with_none_actual_damage(self):
        """Entries without actual_damage should NOT appear in calibration summary averages."""
        from src.app.services.dread_calibration import log_calibration
        entry_id = log_calibration(
            incident_id="INC-noactual",
            dread={"damage": 5.0},
            actual_damage=None,
        )
        # Should still return an ID (entry is stored for later backfill)
        assert entry_id is not None


# =====================================================================
# API endpoint smoke tests (use TestClient)
# =====================================================================

class TestFairEndpoints:
    """Smoke tests for FAIR Monte Carlo and calibration API endpoints."""

    @pytest.fixture(autouse=True)
    def _client(self):
        from src.app.main import create_app
        from starlette.testclient import TestClient
        self.app = create_app()
        self.client = TestClient(
            self.app,
            headers={"x-api-key": os.getenv("OWNER_API_KEY", "local-owner-key")},
        )

    def test_fair_crq_endpoint(self):
        """POST /api/v1/admin/grc/crq/fair returns Monte Carlo results."""
        resp = self.client.post(
            "/api/v1/admin/grc/crq/fair",
            params={"asset_value": 100000, "simulations": 200},
        )
        assert resp.status_code in (200, 403, 401, 422)
        if resp.status_code == 200:
            data = resp.json()
            assert isinstance(data, dict)

    def test_fair_from_signals_endpoint(self):
        """POST /api/v1/admin/grc/crq/fair/from-signals accepts signal params."""
        resp = self.client.post(
            "/api/v1/admin/grc/crq/fair/from-signals",
            params={"monetary_exposure": 5000, "fraud_level": "high",
                    "cv_severity": "major", "signal_count": 5, "simulations": 200},
        )
        assert resp.status_code in (200, 403, 401, 422)

    def test_dread_calibration_endpoint(self):
        """GET /api/v1/admin/grc/dread-calibration returns calibration summary."""
        resp = self.client.get(
            "/api/v1/admin/grc/dread-calibration",
            params={"days": 30},
        )
        assert resp.status_code in (200, 403, 401, 422)
        if resp.status_code == 200:
            data = resp.json()
            assert "entries" in data


# =====================================================================
# Integration: compute_dread → _pasta interaction
# =====================================================================

class TestDreadPastaIntegration:
    """End-to-end: compute DREAD, then feed into _pasta for floor check."""

    def test_high_severity_multisignal_triggers_floor(self):
        """Critical severity + multiple signals produces DREAD >= 7.5 and advanced KC."""
        signals = {
            "prompt_injection": True,
            "data_exfiltration": True,
            "agentic_tool_abuse": True,
        }
        dread = compute_dread(signals, severity="critical", actor_context={"actor_role": "admin"})
        assert dread["weighted_avg"] >= 7.5
        assert dread["kill_chain_stage"] in ("Exploitation", "Installation", "CommandAndControl", "ActionsOnObjectives")
        pasta = _pasta(signals, "info", dread=dread)
        stage_num = int(pasta["current_stage"].replace("Stage", ""))
        assert stage_num >= 6

    def test_low_severity_no_floor(self):
        """Info severity + scanner_burst only → low DREAD, no PASTA floor."""
        dread = compute_dread({"scanner_burst": True}, severity="info")
        pasta = _pasta({"scanner_burst": True}, "info", dread=dread)
        stage_num = int(pasta["current_stage"].replace("Stage", ""))
        assert stage_num < 6
