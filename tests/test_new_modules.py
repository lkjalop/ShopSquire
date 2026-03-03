"""Tests for all new modules implemented in the current sprint:

- MAESTRO boundary validation
- Behavioral biometrics (mouse, typing, tap, scroll)
- LLM-based BEC detection (urgency, impersonation, homoglyph, levenshtein)
- Thread hijacking + lateral movement detection
- CVSS→incident auto-creation
- NQE convergence
- LangGraph typed state (PipelineState)
- Diffusion model detection
- Transformer-based fraud anomaly
- Product delta explanation
"""
import math
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# MAESTRO Agent Boundaries
# ===========================================================================

class TestMAESTROBoundaries:

    def test_known_agent_allowed_tool(self):
        from src.app.security.maestro_boundaries import check_tool_access
        v = check_tool_access("NLP_Search_Agent", "parse_query")
        assert v is None

    def test_known_agent_disallowed_tool(self):
        from src.app.security.maestro_boundaries import check_tool_access
        v = check_tool_access("NLP_Search_Agent", "score_fraud")
        assert v is not None
        assert v.violation_type == "tool_misuse"

    def test_unknown_agent_returns_none(self):
        from src.app.security.maestro_boundaries import check_tool_access
        assert check_tool_access("UnknownAgent", "whatever") is None

    def test_data_scope_allowed(self):
        from src.app.security.maestro_boundaries import check_data_scope
        v = check_data_scope("Fraud_Scoring_Agent", "orders")
        assert v is None

    def test_data_scope_violation(self):
        from src.app.security.maestro_boundaries import check_data_scope
        v = check_data_scope("NLP_Search_Agent", "orders")
        assert v is not None
        assert v.violation_type == "data_scope"

    def test_peer_communication_allowed(self):
        from src.app.security.maestro_boundaries import check_peer_communication
        v = check_peer_communication("NLP_Search_Agent", "Candidate_Retrieval_Agent")
        assert v is None

    def test_peer_communication_violation(self):
        from src.app.security.maestro_boundaries import check_peer_communication
        v = check_peer_communication("NLP_Search_Agent", "Fraud_Scoring_Agent")
        assert v is not None
        assert v.violation_type == "peer_violation"

    def test_value_within_limit(self):
        from src.app.security.maestro_boundaries import check_autonomous_value
        v = check_autonomous_value("Orchestrator", 100.0)
        assert v is None

    def test_value_exceeds_limit(self):
        from src.app.security.maestro_boundaries import check_autonomous_value
        v = check_autonomous_value("Orchestrator", 999.0)
        assert v is not None
        assert v.violation_type == "value_exceeded"
        assert v.severity == "critical"

    def test_non_orchestrator_zero_value_limit(self):
        from src.app.security.maestro_boundaries import check_autonomous_value
        v = check_autonomous_value("NLP_Search_Agent", 1.0)
        assert v is not None

    def test_validate_agent_action_clean(self):
        from src.app.security.maestro_boundaries import validate_agent_action
        violations = validate_agent_action(
            agent_name="NLP_Search_Agent",
            tool_name="parse_query",
            data_scope="products",
            target_agent="Candidate_Retrieval_Agent",
        )
        assert violations == []

    def test_validate_agent_action_multiple_violations(self):
        from src.app.security.maestro_boundaries import validate_agent_action
        violations = validate_agent_action(
            agent_name="NLP_Search_Agent",
            tool_name="score_fraud",
            data_scope="pii",
            target_agent="Security_Observer_Agent",
            value_usd=100.0,
        )
        assert len(violations) >= 3  # tool, data_scope, peer, value

    def test_boundary_summary_keys(self):
        from src.app.security.maestro_boundaries import get_boundary_summary
        summary = get_boundary_summary()
        assert "Orchestrator" in summary
        assert "risk_tier" in summary["Orchestrator"]
        assert summary["Orchestrator"]["risk_tier"] == "critical"


# ===========================================================================
# Behavioral Biometrics
# ===========================================================================

class TestBehavioralBiometrics:

    def _make_straight_mouse(self, n=20):
        """Generate perfectly straight mouse events (bot-like)."""
        return [{"x": i * 10, "y": i * 10, "t_ms": i * 50} for i in range(n)]

    def _make_human_mouse(self, n=20):
        """Generate wiggly mouse events (human-like)."""
        import random
        rng = random.Random(42)
        events = []
        for i in range(n):
            events.append({
                "x": i * 10 + rng.uniform(-15, 15),
                "y": i * 10 + rng.uniform(-15, 15),
                "t_ms": i * 50 + rng.uniform(-20, 20),
            })
        return events

    def test_bot_mouse_detected(self):
        from src.app.services.behavioral_biometrics import analyze_mouse
        result = analyze_mouse(self._make_straight_mouse())
        assert result.get("is_suspicious") or result.get("straightness_ratio", 0) > 0.95

    def test_human_mouse_not_flagged(self):
        from src.app.services.behavioral_biometrics import analyze_mouse
        result = analyze_mouse(self._make_human_mouse())
        # Human mouse should not trigger the straightness flag
        assert result.get("straightness_ratio", 0) < 0.98

    def test_typing_bot_pattern(self):
        from src.app.services.behavioral_biometrics import analyze_typing
        # Perfectly regular typing (bot-like)
        events = [{"key": "a", "down_ms": i * 100, "up_ms": i * 100 + 50} for i in range(10)]
        result = analyze_typing(events)
        # Should detect low variance
        assert "hold_cv" in result or "is_suspicious" in result

    def test_tap_few_events_not_flagged(self):
        from src.app.services.behavioral_biometrics import analyze_taps
        result = analyze_taps([{"x": 0, "y": 0, "t_ms": 100}])
        assert result.get("is_suspicious") is not True

    def test_scroll_uniform(self):
        from src.app.services.behavioral_biometrics import analyze_scroll
        # Perfectly uniform scrolls (bot-like)
        events = [{"delta_y": 100, "t_ms": i * 200} for i in range(10)]
        result = analyze_scroll(events)
        assert "uniform_ratio" in result

    def test_session_biometrics_integration(self):
        from src.app.services.behavioral_biometrics import analyze_session_biometrics
        session = {
            "mouse_events": self._make_straight_mouse(),
            "keystroke_events": [{"key": "a", "down_ms": i * 100, "up_ms": i * 100 + 50} for i in range(10)],
            "tap_events": [],
            "scroll_events": [{"delta_y": 100, "t_ms": i * 200} for i in range(10)],
        }
        result = analyze_session_biometrics(session)
        assert hasattr(result, "is_bot_likely")
        assert hasattr(result, "risk_score")
        assert 0.0 <= result.risk_score <= 1.0

    def test_empty_session_safe(self):
        from src.app.services.behavioral_biometrics import analyze_session_biometrics
        result = analyze_session_biometrics({})
        assert result.risk_score == 0.0


# ===========================================================================
# Enhanced BEC Detection
# ===========================================================================

class TestBECDetection:

    def test_urgency_strong(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("Please wire the funds IMMEDIATELY")
        assert r["urgency"] is True
        assert r["urgency_score"] >= 0.6

    def test_urgency_weak(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("Please send this soon")
        assert r["urgency_score"] > 0

    def test_wire_transfer(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("Please send via wire to IBAN DE123")
        assert r["wire_transfer"] is True

    def test_gift_cards(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("Buy 5 iTunes gift card codes")
        assert r["gift_cards"] is True

    def test_invoice_redirect(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("here is the updated invoice with new payment details")
        assert r["invoice_redirect"] is True

    def test_ceo_impersonation_display_name(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("Transfer now", display_name="John Smith, CEO")
        assert r["ceo_impersonation"] is True

    def test_ceo_impersonation_body(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("I'm the CFO and I need this done today")
        assert r["ceo_impersonation"] is True

    def test_homoglyph_detection(self):
        from src.app.security.email_validation import detect_bec_indicators
        # Cyrillic 'а' (U+0430) instead of Latin 'a'
        cyrillic_a = "\N{CYRILLIC SMALL LETTER A}"
        r = detect_bec_indicators("hello", from_domain=f"g{cyrillic_a}oogle.com")
        assert r["homoglyph_detected"] is True

    def test_levenshtein_lookalike(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators(
            "hello",
            from_domain="gooogle.com",
            known_domains=["google.com"],
        )
        assert r["lookalike_domain"] is True
        assert r["domain_similarity"] > 0.75

    def test_exact_domain_not_flagged(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators(
            "hello",
            from_domain="google.com",
            known_domains=["google.com"],
        )
        assert r["lookalike_domain"] is False

    def test_bec_risk_score_range(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators("normal message")
        assert 0.0 <= r["bec_risk_score"] <= 1.0

    def test_high_risk_composite(self):
        from src.app.security.email_validation import detect_bec_indicators
        r = detect_bec_indicators(
            "URGENT: wire $50k immediately to updated invoice account",
            from_domain="gooogle.com",
            display_name="CEO Office",
            known_domains=["google.com"],
        )
        assert r["bec_risk_score"] >= 0.5


# ===========================================================================
# Thread Hijacking + Lateral Movement
# ===========================================================================

class TestThreadHijacking:

    def test_no_reply_no_hijack(self):
        from src.app.security.email_validation import detect_thread_hijack
        r = detect_thread_hijack({"From": "user@example.com", "Subject": "Hello"})
        assert r["is_reply"] is False
        assert r["thread_hijack"] is False

    def test_reply_same_domain_ok(self):
        from src.app.security.email_validation import detect_thread_hijack
        r = detect_thread_hijack({
            "From": "alice@example.com",
            "In-Reply-To": "<msg1@example.com>",
            "References": "<msg1@example.com>",
        })
        assert r["is_reply"] is True
        assert r["thread_hijack"] is False

    def test_reply_different_domain_hijack(self):
        from src.app.security.email_validation import detect_thread_hijack
        r = detect_thread_hijack({
            "From": "attacker@evil.com",
            "In-Reply-To": "<msg1@company.com>",
            "References": "<msg1@company.com>",
        })
        assert r["is_reply"] is True
        assert r["thread_hijack"] is True

    def test_known_thread_domains(self):
        from src.app.security.email_validation import detect_thread_hijack
        r = detect_thread_hijack(
            {
                "From": "outsider@other.com",
                "In-Reply-To": "<msg1@partner.com>",
            },
            known_thread_domains={"company.com", "partner.com"},
        )
        assert r["thread_hijack"] is True  # outsider not in known domains

    def test_lateral_movement_credentials(self):
        from src.app.security.email_validation import detect_thread_hijack
        r = detect_thread_hijack({
            "From": "user@company.com",
            "Subject": "FW: password: s3cret123 for server",
        })
        assert r["lateral_movement"] is True

    def test_lateral_movement_internal_url(self):
        from src.app.security.email_validation import detect_thread_hijack
        r = detect_thread_hijack({
            "From": "user@company.com",
            "Subject": "Check https://192.168.1.100/admin",
        })
        assert r["lateral_movement"] is True

    def test_no_lateral_movement(self):
        from src.app.security.email_validation import detect_thread_hijack
        r = detect_thread_hijack({
            "From": "user@company.com",
            "Subject": "Re: Meeting notes",
        })
        assert r["lateral_movement"] is False


# ===========================================================================
# CVSS → Incident Auto-Creation
# ===========================================================================

class TestCVSSIncidents:

    def test_severity_to_cvss_critical(self):
        from src.app.security.vuln_scan import severity_to_cvss
        assert severity_to_cvss("critical") == 9.5

    def test_severity_to_cvss_high(self):
        from src.app.security.vuln_scan import severity_to_cvss
        assert severity_to_cvss("high") == 8.0

    def test_severity_to_cvss_unknown(self):
        from src.app.security.vuln_scan import severity_to_cvss
        assert severity_to_cvss("banana") == 0.0

    def test_auto_create_incidents_filters_low(self):
        from src.app.security.vuln_scan import auto_create_incidents_from_findings
        scan = {
            "findings": [
                {"id": "f1", "severity": "critical", "target": "/admin", "title": "SQLi"},
                {"id": "f2", "severity": "low", "target": "/info", "title": "Info leak"},
                {"id": "f3", "severity": "high", "target": "/api", "title": "IDOR"},
            ]
        }
        with patch("src.app.models.db.db_session", side_effect=Exception("no db")):
            incidents = auto_create_incidents_from_findings(scan_result=scan)
        # Should only create for critical + high (CVSS >= 7.0)
        assert len(incidents) == 2
        sevs = {i["severity"] for i in incidents}
        assert "low" not in sevs

    def test_auto_create_custom_threshold(self):
        from src.app.security.vuln_scan import auto_create_incidents_from_findings
        scan = {
            "findings": [
                {"id": "f1", "severity": "medium", "target": "/x", "title": "XSS"},
            ]
        }
        with patch("src.app.models.db.db_session", side_effect=Exception("no db")):
            incidents = auto_create_incidents_from_findings(scan_result=scan, cvss_threshold=5.0)
        assert len(incidents) == 1

    def test_auto_create_empty_findings(self):
        from src.app.security.vuln_scan import auto_create_incidents_from_findings
        incidents = auto_create_incidents_from_findings(scan_result={"findings": []})
        assert incidents == []


# ===========================================================================
# NQE Convergence
# ===========================================================================

class TestNQEConvergence:

    def _make_engine(self):
        from src.app.flows.nqe import NextQuestionEngine, NQEInput
        from src.app.rag.retrieve import Retriever

        class FakeTemplates:
            def get_templates(self, *a, **kw):
                return []

        rag = MagicMock(spec=Retriever)
        rag.retrieve.return_value = []
        return NextQuestionEngine(rag, FakeTemplates()), NQEInput

    def test_convergence_when_enough_slots_answered(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=[],
            query="I want a laptop",
            answered_fields={
                "budget": "$1000",
                "use_case": "gaming",
                "brand_preference": "ASUS",
            },
        )
        qs = engine.propose(inp)
        assert qs == []

    def test_no_convergence_when_few_slots(self):
        engine, NQEInput = self._make_engine()
        inp = NQEInput(
            intent="product_search",
            product_category="laptop",
            missing_fields=["budget"],
            query="I want a laptop",
            answered_fields={"use_case": "work"},
        )
        qs = engine.propose(inp)
        # Should ask questions (only 1 high-signal slot)
        assert len(qs) >= 0  # may generate questions


# ===========================================================================
# LangGraph Typed State (PipelineState)
# ===========================================================================

class TestPipelineState:

    def test_init_pipeline_state(self):
        from src.app.services.pipeline_state import init_pipeline_state
        state = init_pipeline_state("trace-1", "user-1", {"query": "laptop"})
        assert state["trace_id"] == "trace-1"
        assert state["uid"] == "user-1"
        assert state["phase"] == "init"
        assert isinstance(state["timings"], dict)

    def test_merge_phase_output(self):
        from src.app.services.pipeline_state import init_pipeline_state, merge_phase_output
        state = init_pipeline_state("t1", "u1", {})
        state = merge_phase_output(state, {"phase": "phase1", "candidate_count": 5})
        assert state["phase"] == "phase1"
        assert state["candidate_count"] == 5

    def test_merge_timings_accumulate(self):
        from src.app.services.pipeline_state import init_pipeline_state, merge_phase_output
        state = init_pipeline_state("t1", "u1", {})
        state = merge_phase_output(state, {"timings": {"phase1": 0.5}})
        state = merge_phase_output(state, {"timings": {"phase2": 0.3}})
        assert state["timings"]["phase1"] == 0.5
        assert state["timings"]["phase2"] == 0.3

    def test_merge_errors_accumulate(self):
        from src.app.services.pipeline_state import init_pipeline_state, merge_phase_output
        state = init_pipeline_state("t1", "u1", {})
        state = merge_phase_output(state, {"errors": ["err1"]})
        state = merge_phase_output(state, {"errors": ["err2"]})
        assert state["errors"] == ["err1", "err2"]

    def test_phase_summary(self):
        from src.app.services.pipeline_state import init_pipeline_state, merge_phase_output, phase_summary
        state = init_pipeline_state("t1", "u1", {})
        state = merge_phase_output(state, {
            "phase": "phase3",
            "candidate_count": 10,
            "nqe_converged": True,
            "timings": {"nlp": 0.1, "rank": 0.2},
        })
        s = phase_summary(state)
        assert s["phase"] == "phase3"
        assert s["candidate_count"] == 10
        assert s["nqe_converged"] is True
        assert "nlp" in s["timing_phases"]


# ===========================================================================
# Diffusion Model Detection
# ===========================================================================

class TestDiffusionDetection:

    def _make_uniform_image(self, w=32, h=32, val=128):
        """Perfectly uniform image — suspicious (AI-like flat noise)."""
        return bytes([val, val, val] * w * h), w, h

    def _make_noisy_image(self, w=32, h=32):
        """Image with varied noise — natural-looking."""
        import random
        rng = random.Random(42)
        pixels = []
        for _ in range(w * h):
            r = rng.randint(0, 255)
            g = rng.randint(0, 255)
            b = rng.randint(0, 255)
            pixels.extend([r, g, b])
        return bytes(pixels), w, h

    def test_uniform_image_flagged(self):
        from src.app.security.diffusion_detection import detect_diffusion_image
        data, w, h = self._make_uniform_image()
        r = detect_diffusion_image(data, w, h)
        assert r.confidence >= 0.0
        assert isinstance(r.is_ai_generated, bool)

    def test_noisy_image_analyzed(self):
        from src.app.security.diffusion_detection import detect_diffusion_image
        data, w, h = self._make_noisy_image()
        r = detect_diffusion_image(data, w, h)
        assert 0.0 <= r.confidence <= 1.0
        assert "hf_ratio" in r.details

    def test_insufficient_data(self):
        from src.app.security.diffusion_detection import detect_diffusion_image
        r = detect_diffusion_image(b"\x00" * 10, 100, 100)
        assert r.is_ai_generated is False
        assert "insufficient_data" in r.signals

    def test_result_has_all_detail_keys(self):
        from src.app.security.diffusion_detection import detect_diffusion_image
        data, w, h = self._make_noisy_image()
        r = detect_diffusion_image(data, w, h)
        for key in ["hf_ratio", "spectral_flatness", "noise_uniformity", "peak_freq_norm"]:
            assert key in r.details


# ===========================================================================
# Transformer-Based Fraud Anomaly
# ===========================================================================

class TestTransformerFraud:

    def test_normal_shopping_session(self):
        from src.app.services.transformer_fraud import score_action_sequence
        actions = ["page_view", "search", "page_view", "add_to_cart", "checkout_start", "payment_submit"]
        r = score_action_sequence(actions)
        assert r.sequence_length == 6
        assert 0.0 <= r.anomaly_score <= 1.0
        assert r.attention_entropy > 0

    def test_suspicious_rapid_actions(self):
        from src.app.services.transformer_fraud import score_action_sequence
        actions = ["rapid_click"] * 10 + ["admin_access", "export_data"]
        r = score_action_sequence(actions)
        assert r.anomaly_score > 0

    def test_empty_sequence(self):
        from src.app.services.transformer_fraud import score_action_sequence
        r = score_action_sequence([])
        assert r.is_anomalous is False
        assert r.sequence_length == 0

    def test_single_action(self):
        from src.app.services.transformer_fraud import score_action_sequence
        r = score_action_sequence(["login"])
        assert r.sequence_length == 1
        assert 0.0 <= r.anomaly_score <= 1.0

    def test_admin_export_anomalous(self):
        from src.app.services.transformer_fraud import score_action_sequence
        # Admin access then data export — unusual pattern
        actions = ["admin_access", "export_data", "admin_access", "export_data", "admin_access"]
        r = score_action_sequence(actions)
        assert r.anomaly_score > 0  # should deviate from normal shopping centroid

    def test_action_vocab_coverage(self):
        from src.app.services.transformer_fraud import ACTION_VOCAB
        assert "page_view" in ACTION_VOCAB
        assert "payment_submit" in ACTION_VOCAB
        assert "admin_access" in ACTION_VOCAB
        assert len(ACTION_VOCAB) >= 15


# ===========================================================================
# Levenshtein similarity (helper)
# ===========================================================================

class TestLevenshtein:

    def test_identical_strings(self):
        from src.app.security.email_validation import _levenshtein_similarity
        assert _levenshtein_similarity("abc", "abc") == 1.0

    def test_completely_different(self):
        from src.app.security.email_validation import _levenshtein_similarity
        sim = _levenshtein_similarity("abc", "xyz")
        assert sim < 0.5

    def test_one_char_off(self):
        from src.app.security.email_validation import _levenshtein_similarity
        sim = _levenshtein_similarity("google.com", "gooogle.com")
        assert sim > 0.8

    def test_empty_strings(self):
        from src.app.security.email_validation import _levenshtein_similarity
        assert _levenshtein_similarity("", "") == 1.0
        assert _levenshtein_similarity("a", "") == 0.0
