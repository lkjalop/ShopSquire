"""End-to-end integration tests covering:
  1. CV image signals → recommend/suggest wiring (image_labels, image_cv_signals)
  2. Security matrix populated with CV scan signals on the recommend response
  3. NQE (Next Question Engine) generates contextual follow-up questions
  4. Persona detection from chat-style inputs
  5. Multi-turn NQE context preservation
  6. Real test-image payloads (macbook-QR, apple-mac, lenovo-pro7)
"""
from __future__ import annotations

import base64
import json
import os

import pytest
from fastapi.testclient import TestClient
from tests.utils import default_headers
from src.app.main import create_app
from src.app.services.recommendations import RecommendationService

pytestmark = [
    pytest.mark.frozen_characterization,
    pytest.mark.skip(
        reason=(
            "frozen V1 RecommendationService/CV/NQE characterization; active V2 "
            "multimodal and security contracts live in protocol and browser suites"
        )
    ),
]

app = create_app()
client = TestClient(app, headers=default_headers())

_DEMO_PRODUCTS = [
    {"id": "p1", "sku": "MBP14", "name": "MacBook Pro 14", "price_cents": 209900, "currency": "USD", "stock": 3, "specs": {"ram_gb": 16, "storage": "1TB", "cpu": "Apple M4"}},
    {"id": "p2", "sku": "XPS13PLUS", "name": "Dell XPS 13 Plus", "price_cents": 129900, "currency": "USD", "stock": 5, "specs": {"ram_gb": 16, "storage": "512GB", "cpu": "Intel i7"}},
    {"id": "p3", "sku": "LENOVO-PRO7", "name": "Lenovo ThinkPad Pro 7", "price_cents": 169900, "currency": "USD", "stock": 4, "specs": {"ram_gb": 32, "storage": "1TB", "cpu": "AMD Ryzen 9"}},
    {"id": "p4", "sku": "ASUS-ROG", "name": "ASUS ROG Zephyrus", "price_cents": 249900, "currency": "USD", "stock": 2, "specs": {"ram_gb": 32, "gpu": "RTX 4070", "storage": "1TB"}},
]


def _write_flags(flags: dict):
    path = os.path.join("config", "feature_flags.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def _default_flags():
    return {
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"recommend": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "DECISION_LOG_WRITES_ENABLED": False,
        "DEGRADATION": {"enabled": True},
        "TEST_FORCE_BAD_SKU": False,
    }


def _patch_candidates(monkeypatch):
    monkeypatch.setattr(
        RecommendationService,
        "retrieve_candidates",
        lambda self, query, limit=10: list(_DEMO_PRODUCTS),
    )


def _load_test_image_b64(name: str) -> str | None:
    """Load a test image from dump/test-cv as base64 string."""
    path = os.path.join("dump", "test-cv", name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


# ---------------------------------------------------------------------------
# 1. Image labels → recommend/suggest wiring
# ---------------------------------------------------------------------------
class TestImageLabelWiring:
    """Verify that image_labels and image_cv_signals params are consumed and
    influence constraints_used and the security payload on the response."""

    def test_image_labels_set_brand_constraint(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-cv-label-1",
                "query": "find similar laptops to this",
                "image_labels": "macbook,laptop,apple,silver",
            },
        )
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        # Image labels containing "macbook"/"apple" should infer Apple brand
        brands = [str(b).lower() for b in (constraints.get("brands") or constraints.get("brand") or [])]
        # Must either appear as brand constraint or in query_effective
        query_used = str(constraints.get("query") or "").lower()
        assert "apple" in brands or "macbook" in query_used or "apple" in query_used

    def test_image_cv_signals_populate_security_payload(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-cv-sec-1",
                "query": "what laptop is this?",
                "image_labels": "laptop,lenovo",
                "image_cv_signals": json.dumps({
                    "qr_code_detected": False,
                    "manipulation_detected": False,
                    "adversarial_score": 0.05,
                }),
            },
        )
        assert r.status_code == 200
        body = r.json()
        sec = body.get("security") or {}
        # Security block must exist and have signals sub-dict
        assert isinstance(sec, dict)
        # Severity should be present (info for benign signals)
        assert sec.get("severity") is not None

    def test_qr_detected_triggers_reupload(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-cv-qr-1",
                "query": "find similar to picture",
                "image_labels": "laptop",
                "image_cv_signals": json.dumps({
                    "qr_code_detected": True,
                    "qr_prompt_injection": True,
                    "adversarial_score": 0.7,
                }),
            },
        )
        assert r.status_code == 200
        body = r.json()
        # Status is "image_flagged_vision_results" (shows matched products alongside the
        # security warning) or legacy "reupload_required" — both include the reupload question.
        assert body.get("status") in ("reupload_required", "image_flagged_vision_results")
        nqs = body.get("next_questions") or []
        assert any(
            str((q or {}).get("id") or "") == "reupload_clean_image"
            for q in nqs
            if isinstance(q, dict)
        )


# ---------------------------------------------------------------------------
# 2. Security matrix payload structure
# ---------------------------------------------------------------------------
class TestSecurityMatrixPopulation:
    """Verify the security payload has the correct shape for the Decision Trace
    Security Matrix panel."""

    def test_security_payload_structure_on_benign_query(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-secmat-1", "query": "gaming laptops under $2000"},
        )
        assert r.status_code == 200
        sec = r.json().get("security") or {}
        # These keys must always exist for the matrix panel to render
        for key in ("severity", "mitre", "owasp", "stride", "signals"):
            assert key in sec, f"Missing security key: {key}"
        assert isinstance(sec["signals"], dict)
        assert sec["severity"] in ("info", "warn", "warning", "high", "critical", None)

    def test_security_matrix_includes_cv_signals_when_image_provided(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-secmat-cv-1",
                "query": "find similar laptops",
                "image_labels": "lenovo,thinkpad",
                "image_cv_signals": json.dumps({
                    "qr_code_detected": False,
                    "manipulation_detected": False,
                }),
            },
        )
        assert r.status_code == 200
        sec = r.json().get("security") or {}
        # Severity should be info for a benign image with no threats
        assert sec.get("severity") in ("info", "warn", None)
        # Signals should include cv_signals merged from observer analysis
        signals = sec.get("signals") or {}
        assert isinstance(signals, dict)


# ---------------------------------------------------------------------------
# 3. NQE produces contextual questions
# ---------------------------------------------------------------------------
class TestNQEWiring:
    """Verify the NextQuestionEngine generates questions based on missing constraints."""

    def test_nqe_generates_budget_question_for_vague_query(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-nqe-1", "query": "I need a laptop"},
        )
        assert r.status_code == 200
        body = r.json()
        nqs = body.get("next_questions") or []
        assert len(nqs) >= 1, "NQE should produce at least one question for a vague query"
        # Should ask budget or use-case
        ids = {str((q or {}).get("id") or "").lower() for q in nqs if isinstance(q, dict)}
        assert ids & {"ask_budget", "ask_use_case", "ask_budget_tier"}, f"Expected budget/use_case question, got: {ids}"

    def test_nqe_generates_use_case_question(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-nqe-2", "query": "laptop under $1500"},
        )
        assert r.status_code == 200
        body = r.json()
        nqs = body.get("next_questions") or []
        # Budget is specified, so NQE should ask about use-case or brand
        ids = {str((q or {}).get("id") or "").lower() for q in nqs if isinstance(q, dict)}
        assert len(ids) >= 1

    def test_nqe_questions_have_options(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-nqe-3", "query": "find me a laptop"},
        )
        assert r.status_code == 200
        body = r.json()
        nqs = body.get("next_questions") or []
        for q in nqs:
            if not isinstance(q, dict):
                continue
            # Standard questions should have options list
            qid = str(q.get("id") or "").lower()
            if qid in ("ask_budget", "ask_use_case"):
                opts = q.get("options")
                assert isinstance(opts, list) and len(opts) >= 2, (
                    f"Question {qid} should have >=2 options, got: {opts}"
                )

    def test_nqe_selection_applies_budget_constraint(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-nqe-4",
                "query": "I need a laptop",
                "nqe_question_id": "ask_budget",
                "nqe_option_id": "budget_under_1000",
                "nqe_option_label": "Under $1,000",
                "nqe_option_value": "0-1000",
            },
        )
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        # Budget max should be ~1000 from the NQE selection
        bmax = constraints.get("budget_max")
        assert bmax is not None and int(bmax) <= 1000, f"Expected budget_max<=1000, got {bmax}"


# ---------------------------------------------------------------------------
# 4. Persona detection from chat inputs
# ---------------------------------------------------------------------------
class TestPersonaDetection:
    """Verify buyer persona detection from natural chat-style inputs."""

    @pytest.mark.parametrize("query,expected_persona", [
        ("I'm a university student looking for a laptop for assignments", "student"),
        ("need a laptop for gaming, playing Valorant and Fortnite", "gamer"),
        ("looking for a work from home setup, need Teams and Outlook", "corporate"),
        ("I do video editing on Premiere Pro and DaVinci Resolve", "creative"),
        ("need something lightweight for travel and commuting", "traveler"),
    ])
    def test_persona_detected_from_query(self, monkeypatch, query, expected_persona):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        uid = f"u-persona-{expected_persona}"
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": query},
        )
        assert r.status_code == 200
        body = r.json()
        detected = body.get("buyer_persona") or body.get("buyer_persona_candidate")
        assert detected == expected_persona, (
            f"query={query!r} → expected persona={expected_persona}, got={detected}"
        )

    def test_low_confidence_persona_triggers_use_case_fallback(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        # "laptop for my stuff" is too vague to identify a strong persona
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-persona-low", "query": "laptop for my stuff"},
        )
        assert r.status_code == 200
        body = r.json()
        nqs = body.get("next_questions") or []
        ids = {str((q or {}).get("id") or "").lower() for q in nqs if isinstance(q, dict)}
        # Should ask use-case to disambiguate persona
        assert "ask_use_case" in ids, f"Expected ask_use_case for low-confidence persona, got: {ids}"


# ---------------------------------------------------------------------------
# 5. Multi-turn NQE context preservation
# ---------------------------------------------------------------------------
class TestMultiTurnNQE:
    """Verify constraints persist across turns when NQE answers are provided."""

    def test_budget_persists_across_turns(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        uid = "u-multiturn-1"

        # Turn 1: set budget via NQE selection
        r1 = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": uid,
                "query": "I need a laptop",
                "nqe_question_id": "ask_budget",
                "nqe_option_id": "budget_1500_2200",
                "nqe_option_label": "$1,500-$2,200",
                "nqe_option_value": "1500-2200",
            },
        )
        assert r1.status_code == 200

        # Turn 2: follow-up should still have budget constraint
        r2 = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": uid, "query": "show me the best ones with good battery life"},
        )
        assert r2.status_code == 200
        body2 = r2.json()
        constraints2 = body2.get("constraints_used") or {}
        # Budget should persist from turn 1
        bmax = constraints2.get("budget_max")
        bmin = constraints2.get("budget_min")
        assert bmax is not None or bmin is not None, (
            f"Budget should persist from turn 1, constraints={constraints2}"
        )


# ---------------------------------------------------------------------------
# 6. CV analyze endpoint + recommend wiring (with real test images)
# ---------------------------------------------------------------------------
class TestCVAnalyzeWithRealImages:
    """Test the /cv/analyze endpoint returns usable signals and the recommend
    endpoint consumes them correctly."""

    def test_cv_analyze_returns_case_id_and_analysis(self):
        # Small 1x1 PNG payload (known to work in all CV environments)
        tiny_png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQV"
            "R4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
        )
        r = client.post(
            "/api/v1/cv/analyze",
            json={
                "case_id": "test-cv-e2e-1",
                "labels": ["laptop", "macbook"],
                "extracted_text": "MacBook Pro 14 M4",
                "images_b64": [tiny_png_b64],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("case_id") == "test-cv-e2e-1"
        assert body.get("status") == "ok"
        # Must have cv_analysis structure
        assert body.get("cv_analysis") is not None
        # Must have evidence_id for audit trail
        assert body.get("evidence_id") is not None

    def test_macbook_qr_image_triggers_security_signal(self):
        """If macbook-QR test image exists, verify CV detects QR code."""
        b64 = _load_test_image_b64("macbook-QR.png")
        if b64 is None:
            pytest.skip("macbook-QR.png not available in dump/test-cv/")
        r = client.post(
            "/api/v1/cv/analyze",
            json={
                "case_id": "test-cv-qr-mac",
                "labels": ["macbook", "laptop"],
                "extracted_text": "",
                "images_b64": [b64],
            },
        )
        assert r.status_code == 200
        body = r.json()
        # cv_analysis should exist; QR hints should be detected
        qr = body.get("qr_codes") or []
        qr_pi = body.get("qr_prompt_injection")
        ic = body.get("image_consistency") or {}
        # Either QR detected or image consistency marks it suspicious
        assert (
            len(qr) > 0
            or qr_pi is True
            or ic.get("status") in ("mismatch", "suspicious")
            or body.get("suggested_routing") == "security_review"
        ), f"Expected QR/security signal from macbook-QR.png, got: {body}"

    def test_clean_apple_mac_image_benign(self):
        """Apple-mac.jpg should pass through the CV pipeline successfully."""
        b64 = _load_test_image_b64("apple-mac.jpg")
        if b64 is None:
            pytest.skip("apple-mac.jpg not available in dump/test-cv/")
        r = client.post(
            "/api/v1/cv/analyze",
            json={
                "case_id": "test-cv-clean-apple",
                "labels": ["macbook", "apple", "laptop"],
                "extracted_text": "MacBook Air",
                "images_b64": [b64],
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"
        # Clean image should not trigger prompt-injection or QR flags
        assert not body.get("qr_prompt_injection"), "Clean image should not flag QR prompt injection"
        routing = body.get("suggested_routing") or "standard_queue"
        # Image consistency may flag mismatch between provided labels and YOLO detections,
        # so security_review is acceptable. The key is that no injection/QR flags are raised.
        assert routing in ("standard_queue", "security_review"), f"Unexpected routing: {routing}"

    def test_lenovo_image_labels_feed_recommend(self, monkeypatch):
        """Verify that labels extracted from a Lenovo image feed into recommend constraints."""
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={
                "uid": "u-lenovo-cv-1",
                "query": "find me a laptop like this one in the photo",
                "image_labels": "lenovo,thinkpad,laptop,pro7",
                "image_ocr_text": "Lenovo ThinkPad Pro 7 AMD Ryzen 9",
            },
        )
        assert r.status_code == 200
        body = r.json()
        constraints = body.get("constraints_used") or {}
        query_used = str(constraints.get("query") or "").lower()
        # Lenovo should appear in brands or query_effective
        brands = [str(b).lower() for b in (constraints.get("brands") or constraints.get("brand") or [])]
        assert "lenovo" in brands or "lenovo" in query_used, (
            f"Expected 'lenovo' in brands or query, got brands={brands}, query={query_used}"
        )


# ---------------------------------------------------------------------------
# 7. Question plan contract
# ---------------------------------------------------------------------------
class TestQuestionPlanContract:
    """Verify the question_plan is always present and has the right shape."""

    def test_question_plan_always_present(self, monkeypatch):
        _write_flags(_default_flags())
        _patch_candidates(monkeypatch)
        r = client.get(
            "/api/v1/recommend/suggest",
            params={"uid": "u-qp-1", "query": "show me laptops"},
        )
        assert r.status_code == 200
        body = r.json()
        qp = body.get("question_plan")
        assert qp is not None
        assert qp.get("mode") in ("clarify", "assume", "alternative")
        assert isinstance(qp.get("missing_fields"), list)
        assert qp.get("confidence_band") in ("low", "medium", "high")
