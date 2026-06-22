"""Tests for the four digital-marketing enhancements:

  1. ShopperIntentResult dataclass + extract_shopper_intent()
  2. record_commerce_outcome() in decision_log
  3. Seasonal auto-inject via get_active_seasonal_boosts()
  4. Retargeting abandonment trigger (evaluate_cart_abandonment, scan_idle_carts)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# 1. ShopperIntentResult + extract_shopper_intent
# ---------------------------------------------------------------------------
from src.app.services.use_case_advisor import (
    ShopperIntentResult,
    extract_shopper_intent,
)


class TestShopperIntentResult:
    def test_default_values(self):
        r = ShopperIntentResult()
        assert r.persona == "unknown"
        assert r.primary_intent == "recommend"
        assert r.confidence == 0.5
        assert r.price_sensitivity == "medium"
        assert r.urgency == "normal"

    def test_to_dict_roundtrip(self):
        r = ShopperIntentResult(persona="gamer", confidence=0.82)
        d = r.to_dict()
        assert d["persona"] == "gamer"
        assert d["confidence"] == 0.82
        assert "budget_tier" in d
        assert "warranty_tag" in d

    def test_all_fields_present(self):
        d = ShopperIntentResult().to_dict()
        expected = {
            "persona", "primary_intent", "secondary_needs",
            "budget_min", "budget_max", "budget_tier",
            "price_sensitivity", "urgency", "bundle_receptivity",
            "brands_positive", "brands_negative",
            "use_case_key", "accessory_affinities", "priority_factors",
            "confidence", "warranty_tag",
        }
        assert expected == set(d.keys())


class TestExtractShopperIntent:
    """Tests for the intent extraction shim that bridges ParsedQuery → ShopperIntentResult."""

    @staticmethod
    def _make_parsed_query(**overrides):
        """Minimal duck-typed ParsedQuery stand-in."""
        defaults = dict(
            raw_query="I need a gaming laptop under $1500",
            intent="recommend",
            intent_confidence=0.8,
            budget_min=None,
            budget_max=1500,
            specs={},
            brands_positive=["asus"],
            brands_negative=[],
            negations=[],
            use_case_hints=["gaming"],
            mention_count=3,
        )
        defaults.update(overrides)
        return type("FakePQ", (), defaults)()

    def test_gamer_persona(self):
        pq = self._make_parsed_query(use_case_hints=["gaming_competitive"])
        slots = {"use_case": "gaming_competitive"}
        r = extract_shopper_intent(pq, session_slots=slots)
        assert r.persona == "gamer"
        assert r.primary_intent == "recommend"
        assert r.confidence >= 0.7

    def test_office_persona(self):
        pq = self._make_parsed_query(use_case_hints=["office_general"], budget_max=900)
        slots = {"use_case": "office_general"}
        r = extract_shopper_intent(pq, session_slots=slots)
        assert r.persona == "office"

    def test_creator_persona(self):
        pq = self._make_parsed_query(use_case_hints=["content_creator"], budget_max=2000)
        slots = {"use_case": "content_creator"}
        r = extract_shopper_intent(pq, session_slots=slots)
        assert r.persona == "creator"
        assert r.warranty_tag == "warranty_candidate_high"

    def test_student_persona(self):
        pq = self._make_parsed_query(use_case_hints=["university_general"], budget_max=700)
        slots = {"use_case": "university_general"}
        r = extract_shopper_intent(pq, session_slots=slots)
        assert r.persona == "student"

    def test_unknown_persona_fallback(self):
        pq = self._make_parsed_query(use_case_hints=[], budget_max=None)
        r = extract_shopper_intent(pq)
        assert r.persona == "unknown"
        assert r.budget_tier == "unknown"

    def test_budget_tier_classification(self):
        pq = self._make_parsed_query(budget_max=1500)
        r = extract_shopper_intent(pq)
        assert r.budget_tier == "premium"

    def test_high_price_sensitivity(self):
        pq = self._make_parsed_query(budget_max=500)
        r = extract_shopper_intent(pq)
        assert r.price_sensitivity == "high"

    def test_low_price_sensitivity(self):
        pq = self._make_parsed_query(budget_max=2000)
        r = extract_shopper_intent(pq)
        assert r.price_sensitivity == "low"

    def test_brands_propagated(self):
        pq = self._make_parsed_query(brands_positive=["dell", "hp"], brands_negative=["acer"])
        r = extract_shopper_intent(pq)
        assert "dell" in r.brands_positive
        assert "acer" in r.brands_negative

    def test_accessory_affinities_populated(self):
        pq = self._make_parsed_query(use_case_hints=["gaming_competitive"])
        slots = {"use_case": "gaming_competitive"}
        r = extract_shopper_intent(pq, session_slots=slots)
        assert isinstance(r.accessory_affinities, list)
        assert len(r.accessory_affinities) > 0

    def test_urgency_high(self):
        pq = self._make_parsed_query(raw_query="I need a laptop urgently ASAP")
        r = extract_shopper_intent(pq)
        assert r.urgency == "high"

    def test_urgency_low(self):
        pq = self._make_parsed_query(raw_query="just looking around, no rush")
        r = extract_shopper_intent(pq)
        assert r.urgency == "low"

    def test_bundle_receptivity_high_for_recommend_intent(self):
        pq = self._make_parsed_query(intent="recommend")
        r = extract_shopper_intent(pq)
        assert r.bundle_receptivity == "high"

    def test_bundle_receptivity_low_for_budget_shoppers(self):
        pq = self._make_parsed_query(intent="price_check", budget_max=400)
        r = extract_shopper_intent(pq)
        assert r.bundle_receptivity == "low"

    def test_user_profile_fallback(self):
        pq = self._make_parsed_query(use_case_hints=[])
        profile = MagicMock()
        profile.typical_use_cases = ["gaming_competitive", "office_general"]
        r = extract_shopper_intent(pq, user_profile=profile)
        assert r.persona == "gamer"  # first match

    def test_session_slots_override_parsed_query(self):
        pq = self._make_parsed_query(budget_max=None)
        slots = {"budget_max": 800, "use_case": "office_general"}
        r = extract_shopper_intent(pq, session_slots=slots)
        assert r.budget_max == 800
        assert r.persona == "office"


# ---------------------------------------------------------------------------
# 2. record_commerce_outcome
# ---------------------------------------------------------------------------
from src.app.services.decision_log import record_commerce_outcome


class TestRecordCommerceOutcome:
    def test_returns_none_for_empty_decision_id(self):
        assert record_commerce_outcome("") is None
        assert record_commerce_outcome(None) is None

    @patch("src.app.services.decision_log.log_decision")
    def test_calls_log_decision_with_supersede(self, mock_log):
        mock_log.return_value = "outcome-123"
        result = record_commerce_outcome(
            "dec-001",
            upsell_clicked=True,
            bundle_purchased=False,
            coupon_redeemed=True,
            aov_delta_cents=2500,
            conversion=True,
        )
        assert result == "outcome-123"
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args
        assert call_kwargs.kwargs.get("supersedes_decision_id") == "dec-001" or \
               call_kwargs[1].get("supersedes_decision_id") == "dec-001"
        assert call_kwargs.kwargs.get("event_type") == "commerce_outcome" or \
               call_kwargs[1].get("event_type") == "commerce_outcome"

    @patch("src.app.services.decision_log.log_decision")
    def test_outcome_payload_contains_fields(self, mock_log):
        mock_log.return_value = "outcome-456"
        record_commerce_outcome(
            "dec-002",
            fraud_review_triggered=True,
            coupon_risk_score=0.67,
            abuse_signals={"apply_remove_count": 5},
            intervention_type="inline_cart_suggestion",
        )
        call_args = mock_log.call_args
        action = call_args[1].get("proposed_action") or call_args.kwargs.get("proposed_action")
        assert action["fraud_review_triggered"] is True
        assert action["coupon_risk_score"] == 0.67
        assert action["intervention_type"] == "inline_cart_suggestion"
        assert action["abuse_signals"]["apply_remove_count"] == 5

    @patch("src.app.services.decision_log.log_decision", side_effect=Exception("DB down"))
    def test_graceful_failure(self, mock_log):
        import logging
        # Suppress any logging noise from prior tests that may have set the log level
        logging.disable(logging.CRITICAL)
        try:
            result = record_commerce_outcome("dec-003", conversion=False)
        finally:
            logging.disable(logging.NOTSET)
        assert result is None


# ---------------------------------------------------------------------------
# 3. Seasonal auto-inject
# ---------------------------------------------------------------------------
from src.app.services.recommendations import get_active_seasonal_boosts


class TestGetActiveSeasonalBoosts:
    def test_no_active_season_returns_none(self):
        boosts, name = get_active_seasonal_boosts()
        # Default feature_flags.json has active_season: null
        assert boosts is None
        assert name is None

    def test_active_season_returns_boosts(self, tmp_path):
        flags = {
            "SEASONAL_CONTEXT": {
                "active_season": "back_to_school",
                "boosts": {
                    "back_to_school": {"portability": 1.08, "battery": 1.1},
                },
            }
        }
        ff_path = tmp_path / "feature_flags.json"
        ff_path.write_text(json.dumps(flags), encoding="utf-8")
        with patch("src.app.services.recommendations._FEATURE_FLAGS_PATH", str(ff_path)):
            boosts, name = get_active_seasonal_boosts()
        assert name == "back_to_school"
        assert boosts["portability"] == 1.08
        assert boosts["battery"] == 1.1

    def test_missing_file_returns_none(self):
        with patch("src.app.services.recommendations._FEATURE_FLAGS_PATH", "/nonexistent/path.json"):
            boosts, name = get_active_seasonal_boosts()
        assert boosts is None

    def test_invalid_json_returns_none(self, tmp_path):
        ff_path = tmp_path / "feature_flags.json"
        ff_path.write_text("NOT JSON", encoding="utf-8")
        with patch("src.app.services.recommendations._FEATURE_FLAGS_PATH", str(ff_path)):
            boosts, name = get_active_seasonal_boosts()
        assert boosts is None

    def test_active_season_not_in_boosts_returns_none(self, tmp_path):
        flags = {
            "SEASONAL_CONTEXT": {
                "active_season": "summer_sale",
                "boosts": {
                    "back_to_school": {"portability": 1.08},
                },
            }
        }
        ff_path = tmp_path / "feature_flags.json"
        ff_path.write_text(json.dumps(flags), encoding="utf-8")
        with patch("src.app.services.recommendations._FEATURE_FLAGS_PATH", str(ff_path)):
            boosts, name = get_active_seasonal_boosts()
        assert boosts is None


# ---------------------------------------------------------------------------
# 4. Retargeting trigger
# ---------------------------------------------------------------------------
from src.app.services.retargeting_trigger import (
    AbandonmentSignal,
    evaluate_cart_abandonment,
    scan_idle_carts,
    emit_abandonment_event,
)


class TestEvaluateCartAbandonment:
    def test_idle_high_value_triggers(self):
        sig = evaluate_cart_abandonment(
            session_id="sess-1",
            cart_skus=["SKU-A", "SKU-B"],
            cart_value_cents=120000,   # $1200
            last_activity_ts=time.time() - 3600,  # 1h ago
            idle_threshold_sec=1800,
            high_value_cents=80000,
        )
        assert sig is not None
        assert sig.session_id == "sess-1"
        assert sig.cart_value_cents == 120000
        assert sig.idle_seconds >= 3600 - 1   # allow 1s tolerance
        assert sig.confidence > 0.5

    def test_recent_activity_does_not_trigger(self):
        sig = evaluate_cart_abandonment(
            session_id="sess-2",
            cart_skus=["SKU-A"],
            cart_value_cents=120000,
            last_activity_ts=time.time() - 60,  # 1 min ago
            idle_threshold_sec=1800,
            high_value_cents=80000,
        )
        assert sig is None

    def test_low_value_cart_does_not_trigger(self):
        sig = evaluate_cart_abandonment(
            session_id="sess-3",
            cart_skus=["SKU-A"],
            cart_value_cents=5000,   # $50
            last_activity_ts=time.time() - 3600,
            idle_threshold_sec=1800,
            high_value_cents=80000,
        )
        assert sig is None

    def test_nudge_inline_for_short_idle(self):
        sig = evaluate_cart_abandonment(
            session_id="sess-4",
            cart_skus=["SKU-A"],
            cart_value_cents=120000,
            last_activity_ts=time.time() - 2000,
            idle_threshold_sec=1800,
            high_value_cents=80000,
        )
        assert sig is not None
        assert sig.suggested_action == "nudge_inline"

    def test_push_for_mobile(self):
        sig = evaluate_cart_abandonment(
            session_id="sess-5",
            cart_skus=["SKU-A"],
            cart_value_cents=120000,
            last_activity_ts=time.time() - 7200,  # well past threshold
            idle_threshold_sec=1800,
            high_value_cents=80000,
            channel="app",
        )
        assert sig is not None
        assert sig.suggested_action == "retarget_push"

    def test_email_for_long_idle_web(self):
        sig = evaluate_cart_abandonment(
            session_id="sess-6",
            cart_skus=["SKU-A"],
            cart_value_cents=120000,
            last_activity_ts=time.time() - 7200,
            idle_threshold_sec=1800,
            high_value_cents=80000,
            channel="web",
        )
        assert sig is not None
        assert sig.suggested_action == "retarget_email"

    def test_persona_propagated(self):
        sig = evaluate_cart_abandonment(
            session_id="sess-7",
            cart_skus=["SKU-A"],
            cart_value_cents=120000,
            last_activity_ts=time.time() - 3600,
            persona="gamer",
            use_case_key="gaming_competitive",
            idle_threshold_sec=1800,
            high_value_cents=80000,
        )
        assert sig.inferred_persona == "gamer"
        assert sig.use_case_key == "gaming_competitive"


class TestScanIdleCarts:
    def test_filters_qualifying_sessions(self):
        now = time.time()
        sessions = [
            {"session_id": "a", "cart_skus": ["X"], "cart_value_cents": 100000, "last_activity_ts": now - 3600},
            {"session_id": "b", "cart_skus": ["Y"], "cart_value_cents": 5000, "last_activity_ts": now - 3600},  # low value
            {"session_id": "c", "cart_skus": ["Z"], "cart_value_cents": 100000, "last_activity_ts": now - 60},   # recent
        ]
        signals = scan_idle_carts(sessions, idle_threshold_sec=1800, high_value_cents=80000)
        assert len(signals) == 1
        assert signals[0].session_id == "a"

    def test_empty_input(self):
        assert scan_idle_carts([]) == []

    def test_malformed_sessions_skipped(self):
        signals = scan_idle_carts([{"broken": True}], idle_threshold_sec=1, high_value_cents=1)
        assert signals == []


class TestAbandonmentSignal:
    def test_to_dict(self):
        sig = AbandonmentSignal(session_id="s1", cart_value_cents=50000, cart_skus=["A"])
        d = sig.to_dict()
        assert d["session_id"] == "s1"
        assert d["cart_value_cents"] == 50000
        assert "suggested_action" in d

    def test_confidence_capped(self):
        sig = evaluate_cart_abandonment(
            session_id="cap",
            cart_skus=["A"],
            cart_value_cents=99999999,  # enormous
            last_activity_ts=0,         # very old
            idle_threshold_sec=1,
            high_value_cents=1,
        )
        assert sig.confidence <= 0.95


class TestEmitAbandonmentEvent:
    @patch("src.app.services.decision_log.record_commerce_outcome", return_value="out-1")
    @patch("src.app.services.decision_log.log_trace_event")
    def test_emits_trace_and_outcome(self, mock_trace, mock_outcome):
        sig = AbandonmentSignal(
            session_id="sess-e1",
            cart_value_cents=100000,
            cart_skus=["SKU-A"],
        )
        result = emit_abandonment_event(sig, trace_id="tr-1", decision_id="dec-1")
        assert result == "out-1"
        mock_trace.assert_called_once()
        mock_outcome.assert_called_once()

    @patch("src.app.services.decision_log.record_commerce_outcome")
    @patch("src.app.services.decision_log.log_trace_event")
    def test_no_trace_without_trace_id(self, mock_trace, mock_outcome):
        sig = AbandonmentSignal(session_id="sess-e2", cart_value_cents=100000)
        emit_abandonment_event(sig, trace_id=None, decision_id="dec-2")
        mock_trace.assert_not_called()
        mock_outcome.assert_called_once()


# ---------------------------------------------------------------------------
# Round 3: retargeting webhook dispatch tests
# ---------------------------------------------------------------------------
from src.app.services.retargeting_trigger import _load_retargeting_webhook_urls, _dispatch_retargeting_webhooks


class TestLoadRetargetingWebhookUrls:
    def test_returns_empty_for_empty_list(self, tmp_path):
        yml = tmp_path / "webhooks.yml"
        yml.write_text("webhooks:\n  retargeting_events: []\n", encoding="utf-8")
        with patch("src.app.services.retargeting_trigger._WEBHOOKS_YML", str(yml)):
            urls = _load_retargeting_webhook_urls()
        assert urls == []

    def test_returns_urls_when_configured(self, tmp_path):
        yml = tmp_path / "webhooks.yml"
        yml.write_text(
            "webhooks:\n  retargeting_events:\n    - https://hooks.example.com/retarget\n    - https://api.example.org/push\n",
            encoding="utf-8",
        )
        with patch("src.app.services.retargeting_trigger._WEBHOOKS_YML", str(yml)):
            urls = _load_retargeting_webhook_urls()
        assert urls == ["https://hooks.example.com/retarget", "https://api.example.org/push"]

    def test_graceful_degradation_missing_file(self, tmp_path):
        missing = str(tmp_path / "nonexistent.yml")
        with patch("src.app.services.retargeting_trigger._WEBHOOKS_YML", missing):
            urls = _load_retargeting_webhook_urls()
        assert urls == []

    def test_graceful_degradation_malformed_yaml(self, tmp_path):
        yml = tmp_path / "webhooks.yml"
        yml.write_text("{{{{ not valid yaml", encoding="utf-8")
        with patch("src.app.services.retargeting_trigger._WEBHOOKS_YML", str(yml)):
            urls = _load_retargeting_webhook_urls()
        assert urls == []

    def test_ignores_non_string_entries(self, tmp_path):
        yml = tmp_path / "webhooks.yml"
        yml.write_text(
            "webhooks:\n  retargeting_events:\n    - https://valid.example.com/\n    - 12345\n    - null\n",
            encoding="utf-8",
        )
        with patch("src.app.services.retargeting_trigger._WEBHOOKS_YML", str(yml)):
            urls = _load_retargeting_webhook_urls()
        # non-strings are cast, but None/int entries that are falsy are excluded
        assert "https://valid.example.com/" in urls


class TestDispatchRetargetingWebhooks:
    def _make_signal(self) -> AbandonmentSignal:
        return AbandonmentSignal(
            session_id="sess-wh1",
            cart_value_cents=150000,
            cart_skus=["SKU-X"],
            inferred_persona="gamer",
            suggested_action="retarget_email",
            confidence=0.8,
        )

    @patch("src.app.services.webhook_dispatcher.enqueue_webhook")
    @patch("src.app.services.retargeting_trigger._load_retargeting_webhook_urls")
    def test_enqueues_for_each_url(self, mock_urls, mock_enqueue):
        mock_urls.return_value = [
            "https://hooks.example.com/retarget",
            "https://api.example.org/push",
        ]
        _dispatch_retargeting_webhooks(self._make_signal(), decision_id="dec-99", trace_id="tr-99")
        assert mock_enqueue.call_count == 2
        for call in mock_enqueue.call_args_list:
            _id, url, payload = call.args
            assert payload["session_id"] == "sess-wh1"
            assert payload["event"] == "cart_abandonment_detected"
            assert payload["inferred_persona"] == "gamer"

    @patch("src.app.services.retargeting_trigger._load_retargeting_webhook_urls")
    def test_no_dispatch_when_empty_urls(self, mock_urls):
        mock_urls.return_value = []
        # Should not raise and should not import webhook_dispatcher at all
        _dispatch_retargeting_webhooks(self._make_signal())

    @patch("src.app.services.webhook_dispatcher.enqueue_webhook")
    @patch("src.app.services.retargeting_trigger._load_retargeting_webhook_urls")
    def test_emit_abandonment_event_dispatches_webhooks(self, mock_urls, mock_enqueue):
        """Full integration: emit_abandonment_event calls webhooks when configured."""
        mock_urls.return_value = ["https://hooks.example.com/retarget"]
        sig = self._make_signal()
        with (
            patch("src.app.services.decision_log.log_trace_event"),
            patch("src.app.services.decision_log.record_commerce_outcome", return_value="oc-1"),
        ):
            result = emit_abandonment_event(sig, trace_id="tr-100", decision_id="dec-100")
        assert result == "oc-1"
        mock_enqueue.assert_called_once()
        _id, url, payload = mock_enqueue.call_args.args
        assert url == "https://hooks.example.com/retarget"
        assert payload["session_id"] == "sess-wh1"

    @patch("src.app.services.webhook_dispatcher.enqueue_webhook", side_effect=RuntimeError("network"))
    @patch("src.app.services.retargeting_trigger._load_retargeting_webhook_urls")
    def test_webhook_failure_does_not_raise(self, mock_urls, mock_enqueue):
        """Webhook errors must not propagate — abandonment emission must still succeed."""
        mock_urls.return_value = ["https://hooks.example.com/retarget"]
        sig = self._make_signal()
        # Should not raise even if enqueue_webhook throws
        _dispatch_retargeting_webhooks(sig)


# ---------------------------------------------------------------------------
# Round-4 additions: persona-aware assistant messages + checkout-initiate API
# ---------------------------------------------------------------------------


class TestDeterministicAssistantMessagePersona:
    """_deterministic_assistant_message should produce persona-aware, human-like text."""

    def _fn(self):
        from src.app.routers.recommend import _deterministic_assistant_message
        return _deterministic_assistant_message

    def _make_results(self, n: int = 3) -> list:
        return [{"name": f"Product {i}", "sku": f"sku-{i}", "price_cents": 100000, "factors": {"positive": []}} for i in range(n)]

    def test_no_results_returns_recovery_message(self):
        # CRAG never-dead-end contract: zero results yields a non-empty recovery
        # message (NOT None) with an explicit upgrade path, never a blank reply.
        # This matches the authoritative test_deterministic_message_recovery_on_empty
        # in tests/services/test_recommend_budget_advisor.py and the documented
        # "never-empty safety net" branch in recommend_budget_advisor.
        msg = self._fn()("any query", [], {})
        assert msg and "couldn't find" in msg.lower()

    def test_basic_message_uses_i_ve_found(self):
        msg = self._fn()("laptop", self._make_results(), {})
        assert msg is not None
        assert "I've found" in msg

    def test_budget_max_formatted_with_commas(self):
        msg = self._fn()("laptop", self._make_results(), {"budget_max": 1500})
        assert "1,500" in msg
        assert "under $1,500" in msg

    def test_budget_range_formatted(self):
        msg = self._fn()("laptop", self._make_results(), {"budget_min": 1000, "budget_max": 2000})
        assert "1,000" in msg
        assert "2,000" in msg

    def test_gamer_persona_opening(self):
        msg = self._fn()("gaming laptop", self._make_results(), {"buyer_persona": "gamer"})
        assert msg is not None
        assert "gaming setup" in msg

    def test_student_persona_opening(self):
        msg = self._fn()("student laptop", self._make_results(), {"buyer_persona": "student"})
        assert msg is not None
        assert "student-friendly" in msg

    def test_use_case_gaming_opening(self):
        msg = self._fn()("laptop", self._make_results(), {"use_case": "gaming"})
        assert msg is not None
        assert "gaming setup" in msg

    def test_office_use_case_opening(self):
        msg = self._fn()("work laptop", self._make_results(), {"use_case": "office_general"})
        assert msg is not None
        assert "productivity" in msg

    def test_creative_persona_opening(self):
        msg = self._fn()("video editing", self._make_results(), {"use_case": "content_creator"})
        assert msg is not None
        assert "creative" in msg

    def test_urgency_high_adds_stock_note(self):
        constraints = {"shopper_intent": {"persona": "student", "urgency": "high", "bundle_receptivity": "low"}}
        msg = self._fn()("laptop", self._make_results(), constraints)
        assert msg is not None
        assert "stock" in msg or "dispatch" in msg

    def test_bundle_receptivity_high_changes_closing(self):
        constraints = {"shopper_intent": {"bundle_receptivity": "high"}}
        msg = self._fn()("laptop", self._make_results(), constraints)
        assert msg is not None
        assert "bundle" in msg

    def test_shopper_intent_persona_takes_priority(self):
        constraints = {"shopper_intent": {"persona": "gamer"}, "buyer_persona": "student"}
        msg = self._fn()("laptop", self._make_results(), constraints)
        assert msg is not None
        assert "gaming setup" in msg

    def test_pluralization_one_result(self):
        msg = self._fn()("laptop", self._make_results(1), {})
        assert msg is not None
        # Should say "option" not "options"
        assert "1 option" in msg

    def test_pluralization_multiple_results(self):
        msg = self._fn()("laptop", self._make_results(5), {})
        assert msg is not None
        assert "5 options" in msg


class TestCheckoutInitiateEndpoint:
    """POST /api/v1/payments/checkout-initiate — fail-closed outside explicit demo mode."""

    def _get_app(self):
        """Import and return a minimal FastAPI test client for the payments router."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.app.routers.payments import router
        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_returns_503_when_provider_missing_and_demo_not_allowed(self):
        from unittest.mock import patch
        client = self._get_app()
        settings = type("S", (), {"stripe_api_key": "", "feature_flags_path": "unused", "app_env": "prod"})()
        with patch("src.app.routers.payments.get_settings", return_value=settings):
            with patch("src.app.routers.payments.load_feature_flags", return_value={"CAPABILITIES": {"payments": {"enabled": True}}}):
                resp = client.post("/api/v1/payments/checkout-initiate", json={"amount_cents": 99900, "currency": "USD"})
        assert resp.status_code == 503

    def test_returns_real_intent_when_provider_configured(self):
        from unittest.mock import patch
        client = self._get_app()
        settings = type("S", (), {"stripe_api_key": "sk_live_123", "feature_flags_path": "unused", "app_env": "prod"})()
        with patch("src.app.routers.payments.get_settings", return_value=settings):
            with patch("src.app.routers.payments.load_feature_flags", return_value={"CAPABILITIES": {"payments": {"enabled": True}}}):
                with patch("src.app.routers.payments.StripeClient") as mock_client:
                    mock_client.return_value.create_payment_intent.return_value = {
                        "id": "pi_live_123",
                        "client_secret": "cs_live_123",
                    }
                    resp = client.post("/api/v1/payments/checkout-initiate", json={"amount_cents": 5000, "currency": "AUD"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["currency"] == "AUD"
        assert body["demo_mode"] is False
        assert body["status"] == "requires_payment"
        assert body["client_secret"] == "cs_live_123"

    def test_demo_mode_requires_explicit_override(self):
        from unittest.mock import patch
        client = self._get_app()
        settings = type("S", (), {"stripe_api_key": "", "feature_flags_path": "unused", "app_env": "prod"})()
        with patch.dict(os.environ, {"ALLOW_DEMO_CHECKOUT": "1"}, clear=False):
            with patch("src.app.routers.payments.get_settings", return_value=settings):
                with patch("src.app.routers.payments.load_feature_flags", return_value={"CAPABILITIES": {"payments": {"enabled": True}}}):
                    resp = client.post("/api/v1/payments/checkout-initiate", json={"amount_cents": 12345})
        assert resp.status_code == 200
        body = resp.json()
        assert body["amount_cents"] == 12345
        assert body["demo_mode"] is True
        assert body["order_id"].startswith("DEMO-")

    def test_does_not_require_auth_header(self):
        """No x-api-key or Authorization header needed — customer-accessible."""
        from unittest.mock import patch
        client = self._get_app()
        settings = type("S", (), {"stripe_api_key": "", "feature_flags_path": "unused", "app_env": "prod"})()
        with patch("src.app.routers.payments.get_settings", return_value=settings):
            with patch("src.app.routers.payments.load_feature_flags", return_value={"CAPABILITIES": {"payments": {"enabled": True}}}):
                resp = client.post("/api/v1/payments/checkout-initiate", json={})
        assert resp.status_code == 503

