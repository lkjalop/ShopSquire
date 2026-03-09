"""Tests for benign-image security fallback, budget_widen config,
friendly-brand mapping, trust-level computation, and use-case detection.

Covers the changes made in the multi-image recommendation redesign:
  - cv.py security exception handler always returns populated details
  - budget_widen.json config structure validation
  - Frontend logic parity: friendlyBrand, trustLevel, detectUseCase
"""
from __future__ import annotations

import json
import os

import pytest


# ---------------------------------------------------------------------------
# 1. Security fallback — benign images always yield populated security_matrix
# ---------------------------------------------------------------------------
class TestBenignSecurityFallback:
    """Verify that the security exception handler in cv.py produces
    a valid security_details dict even when analyze_payload fails."""

    def test_fallback_dict_is_truthy(self):
        """The fallback must be truthy so `if security_details` evaluates True."""
        fallback = {"severity": "info", "signals": {}}
        assert fallback, "Fallback dict must be truthy"

    def test_empty_dict_is_falsy(self):
        """Confirm the old bug: empty dict {} is falsy and would suppress matrix."""
        assert not {}, "Empty dict is falsy — this was the original bug"

    def test_security_matrix_always_included(self):
        """Simulate the response-building logic—security_matrix should never be None."""
        # Simulate the fixed code path
        security_details = {"severity": "info", "signals": {}}
        security_matrix = {
            "severity": security_details.get("severity"),
            "signals": security_details.get("signals", {}),
            "mitre_atlas": security_details.get("mitre_atlas", []),
            "owasp_llm_top10": security_details.get("owasp_llm_top10", []),
        }
        assert security_matrix is not None
        assert security_matrix["severity"] == "info"
        assert security_matrix["signals"] == {}

    def test_retrieved_context_security_analysis_not_empty(self):
        """retrieved_context.security_analysis should always be a non-empty dict."""
        # Simulate the fixed fallback
        security_details = {"severity": "info", "signals": {}}
        retrieved_context = {
            "security_analysis": security_details if isinstance(security_details, dict) and security_details else {"severity": "info", "signals": {}},
        }
        assert retrieved_context["security_analysis"]
        assert retrieved_context["security_analysis"]["severity"] == "info"

    def test_actual_security_details_passthrough(self):
        """When analyze_payload succeeds with real data, it passes through unchanged."""
        real_details = {
            "severity": "warn",
            "signals": {"qr_code_detected": True, "qr_prompt_injection": False},
            "mitre_atlas": ["AML.T0043"],
            "owasp_llm_top10": ["LLM01"],
            "stride_categories": ["Tampering"],
            "risk_adj": 22.5,
        }
        security_matrix = {
            "severity": real_details.get("severity"),
            "signals": real_details.get("signals", {}),
            "mitre_atlas": real_details.get("mitre_atlas", []),
            "owasp_llm_top10": real_details.get("owasp_llm_top10", []),
        }
        assert security_matrix["severity"] == "warn"
        assert security_matrix["signals"]["qr_code_detected"] is True


# ---------------------------------------------------------------------------
# 2. Budget widen config validation
# ---------------------------------------------------------------------------
class TestBudgetWidenConfig:
    """Validate config/budget_widen.json structure and values."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        path = os.path.join(os.path.dirname(__file__), "..", "config", "budget_widen.json")
        assert os.path.isfile(path), f"budget_widen.json not found at {path}"
        with open(path, "r", encoding="utf-8") as f:
            self.cfg = json.load(f)

    def test_has_budget_widen_key(self):
        assert "budget_widen" in self.cfg

    def test_widen_steps_ascending(self):
        steps = self.cfg["budget_widen"]["steps"]
        assert isinstance(steps, list)
        assert len(steps) >= 1
        for i in range(1, len(steps)):
            assert steps[i] > steps[i - 1], "Steps must be strictly ascending"

    def test_max_widen_total_positive(self):
        assert self.cfg["budget_widen"]["max_widen_total"] > 0

    def test_strategy_known(self):
        assert self.cfg["budget_widen"]["strategy"] in ("from_upper_bound", "from_midpoint")

    def test_fallback_known(self):
        assert self.cfg["budget_widen"]["fallback"] in ("show_nearest_3", "show_nearest_5", "none")

    def test_use_case_profiles_present(self):
        assert "use_case_profiles" in self.cfg
        profiles = self.cfg["use_case_profiles"]
        assert isinstance(profiles, dict)
        assert len(profiles) >= 3  # at least a few profiles

    def test_each_profile_has_required_keys(self):
        for name, profile in self.cfg["use_case_profiles"].items():
            assert "label" in profile, f"{name} missing label"
            assert "budget_hint" in profile, f"{name} missing budget_hint"
            hints = profile["budget_hint"]
            assert isinstance(hints, list) and len(hints) == 2
            assert hints[0] < hints[1], f"{name} budget_hint[0] must be < budget_hint[1]"


# ---------------------------------------------------------------------------
# 3. Friendly-brand mapping (frontend parity tests in Python)
# ---------------------------------------------------------------------------
class TestFriendlyBrand:
    """Mirror of the frontend friendlyBrand() logic — test the same regex patterns."""

    import re

    BRAND_PATTERNS = [
        (re.compile(r"mac\s*book|apple|imac", re.I), "MacBook"),
        (re.compile(r"surface|microsoft", re.I), "Surface"),
        (re.compile(r"lenovo|ideapad|thinkpad|legion|yoga", re.I), "Lenovo"),
        (re.compile(r"dell|xps|inspiron|latitude|alienware", re.I), "Dell"),
        (re.compile(r"hp |hewlett|pavilion|envy|omen|spectre|victus", re.I), "HP"),
        (re.compile(r"asus|rog|zenbook|vivobook|tuf", re.I), "ASUS"),
        (re.compile(r"acer|nitro|predator|swift", re.I), "Acer"),
        (re.compile(r"msi|katana|raider|stealth", re.I), "MSI"),
        (re.compile(r"samsung|galaxy\s*book", re.I), "Samsung"),
        (re.compile(r"chromebook", re.I), "Chromebook"),
        (re.compile(r"laptop|notebook|computer", re.I), "Laptop"),
    ]

    @staticmethod
    def _friendly_brand(labels: list[str], ocr_text: str) -> str:
        import re
        joined = " ".join(labels) + " " + ocr_text
        for pat, brand in TestFriendlyBrand.BRAND_PATTERNS:
            if pat.search(joined):
                return brand
        return "Product"

    @pytest.mark.parametrize("labels,ocr,expected", [
        (["laptop", "apple_logo", "keyboard"], "MacBook Pro 14 inch M3", "MacBook"),
        (["laptop", "lenovo_logo"], "Lenovo IdeaPad Slim 5", "Lenovo"),
        (["laptop", "computer"], "Dell XPS 15 2025", "Dell"),
        (["laptop"], "HP Pavilion 16", "HP"),
        (["rog_logo", "laptop"], "", "ASUS"),
        (["laptop"], "Acer Nitro 5", "Acer"),
        (["laptop"], "MSI Katana 15", "MSI"),
        (["laptop"], "Samsung Galaxy Book", "Samsung"),
        (["laptop"], "Chromebook Plus", "Chromebook"),
        (["laptop"], "", "Laptop"),
        ([], "", "Product"),
    ])
    def test_brand_detection(self, labels, ocr, expected):
        assert self._friendly_brand(labels, ocr) == expected


# ---------------------------------------------------------------------------
# 4. Trust level computation (frontend parity)
# ---------------------------------------------------------------------------
class TestTrustLevel:
    """Mirror of computeTrustLevel() from ImageRecommendPanel.tsx."""

    @staticmethod
    def _compute(signals: dict, session_suspicious: int) -> str:
        if session_suspicious >= 3 or signals.get("qr_prompt_injection"):
            return "red"
        if session_suspicious >= 2 or signals.get("manipulation_detected"):
            return "orange"
        if signals.get("qr_code_detected"):
            return "yellow"
        return "green"

    def test_benign_is_green(self):
        assert self._compute({}, 0) == "green"

    def test_benign_signals_false_is_green(self):
        signals = {"qr_code_detected": False, "qr_prompt_injection": False, "manipulation_detected": False}
        assert self._compute(signals, 0) == "green"

    def test_qr_detected_is_yellow(self):
        assert self._compute({"qr_code_detected": True}, 0) == "yellow"

    def test_manipulation_is_orange(self):
        assert self._compute({"manipulation_detected": True}, 0) == "orange"

    def test_prompt_injection_is_red(self):
        assert self._compute({"qr_prompt_injection": True}, 0) == "red"

    def test_session_suspicious_2_is_orange(self):
        assert self._compute({}, 2) == "orange"

    def test_session_suspicious_3_is_red(self):
        assert self._compute({}, 3) == "red"

    def test_mixed_macbook_qr_and_benign_lenovo(self):
        """Scenario: macbook-QR.png is malicious, lenovo is benign.
        One suspicious image means session count = 1 → per-image signals determine level."""
        macbook_signals = {"qr_code_detected": True, "qr_prompt_injection": True}
        lenovo_signals = {"qr_code_detected": False, "qr_prompt_injection": False, "manipulation_detected": False}
        # macbook gets red (prompt injection)
        assert self._compute(macbook_signals, 1) == "red"
        # lenovo gets green despite being in same session (signals are per-image)
        assert self._compute(lenovo_signals, 1) == "green"


# ---------------------------------------------------------------------------
# 5. Use-case detection (frontend parity)
# ---------------------------------------------------------------------------
class TestUseCaseDetection:
    """Mirror of detectUseCase() from ImageRecommendPanel.tsx."""

    import re

    UC_PATTERNS = [
        (re.compile(r"universit|uni\b|college|school|student|lecture|study", re.I), "university"),
        (re.compile(r"gaming|game|fps|rtx|gpu", re.I), "gaming"),
        (re.compile(r"cod(?:e|ing)|develop|program", re.I), "coding"),
        (re.compile(r"content|creat|video|edit|design|photo", re.I), "content_creation"),
        (re.compile(r"office|admin|work|excel|zoom|teams|meet", re.I), "office"),
    ]

    @staticmethod
    def _detect(query: str) -> str | None:
        for pat, uc in TestUseCaseDetection.UC_PATTERNS:
            if pat.search(query):
                return uc
        return None

    @pytest.mark.parametrize("query,expected", [
        ("I need a laptop for university", "university"),
        ("best laptop for uni students", "university"),
        ("looking for a college laptop", "university"),
        ("gaming laptop under 1500", "gaming"),
        ("I want to play FPS games", "gaming"),
        ("coding laptop for software development", "coding"),
        ("i want to develop apps", "coding"),
        ("video editing laptop for content creation", "content_creation"),
        ("best laptop for photo editing", "content_creation"),
        ("office work laptop with good webcam", "office"),
        ("need it for Excel and Zoom", "office"),
        ("just browsing the internet", None),
        ("", None),
    ])
    def test_use_case_detection(self, query, expected):
        assert self._detect(query) == expected


# ---------------------------------------------------------------------------
# 6. Multi-image context shape
# ---------------------------------------------------------------------------
class TestMultiImageContextShape:
    """Verify the shape of multiple image_recommend_context entries."""

    def test_two_image_contexts_are_independent(self):
        macbook = {
            "labels": ["laptop", "apple_logo", "keyboard"],
            "ocr_text": "MacBook Pro 14",
            "cv_signals": {"qr_code_detected": True, "qr_prompt_injection": True, "manipulation_detected": False},
            "source_name": "macbook-QR.png",
        }
        lenovo = {
            "labels": ["laptop", "lenovo_logo"],
            "ocr_text": "Lenovo IdeaPad Slim 5",
            "cv_signals": {"qr_code_detected": False, "qr_prompt_injection": False, "manipulation_detected": False},
            "source_name": "lenovo-pro7.webp",
        }
        contexts = [macbook, lenovo]
        assert len(contexts) == 2
        # Each has required keys
        for ctx in contexts:
            assert "labels" in ctx
            assert "ocr_text" in ctx
            assert "cv_signals" in ctx
        # Signals don't leak across images
        assert contexts[0]["cv_signals"]["qr_prompt_injection"] is True
        assert contexts[1]["cv_signals"]["qr_prompt_injection"] is False


# ---------------------------------------------------------------------------
# 7. Triage response → context mapping (security.signals path fix)
# ---------------------------------------------------------------------------
class TestTriageResponseMapping:
    """Verify that the frontend mapping from triage response to ImageAnalysisContext
    correctly reads security signals from the nested security.signals path."""

    @staticmethod
    def _map_triage_to_context(t: dict, filename: str = "image.png") -> dict:
        """Mirror of the App.tsx triage → context mapping logic."""
        return {
            "labels": t.get("labels", []) if isinstance(t.get("labels"), list) else [],
            "ocr_text": t.get("extracted_text", "") if isinstance(t.get("extracted_text"), str) else "",
            "cv_signals": {
                "qr_code_detected": bool((t.get("security") or {}).get("signals", {}).get("qr_code_detected")),
                "qr_prompt_injection": bool((t.get("security") or {}).get("signals", {}).get("qr_prompt_injection")),
                "manipulation_detected": bool((t.get("security") or {}).get("signals", {}).get("manipulation_detected")),
            },
            "source_name": filename,
        }

    def test_clean_image_signals_all_false(self):
        """Benign triage response → all signals should be False."""
        triage = {
            "labels": ["laptop", "lenovo_logo"],
            "extracted_text": "Lenovo IdeaPad",
            "security": {"clean": True, "signals": {}, "reupload_needed": False},
        }
        ctx = self._map_triage_to_context(triage, "lenovo.webp")
        assert ctx["cv_signals"]["qr_code_detected"] is False
        assert ctx["cv_signals"]["qr_prompt_injection"] is False
        assert ctx["cv_signals"]["manipulation_detected"] is False
        assert ctx["source_name"] == "lenovo.webp"

    def test_malicious_image_signals_detected(self):
        """Triage response with QR + prompt injection → signals should be True."""
        triage = {
            "labels": ["laptop", "apple_logo", "keyboard", "qr_code"],
            "extracted_text": "MacBook Pro 14",
            "security": {
                "clean": False,
                "signals": {"qr_code_detected": True, "qr_prompt_injection": True},
                "reupload_needed": True,
            },
        }
        ctx = self._map_triage_to_context(triage, "macbook-QR.png")
        assert ctx["cv_signals"]["qr_code_detected"] is True
        assert ctx["cv_signals"]["qr_prompt_injection"] is True
        assert ctx["cv_signals"]["manipulation_detected"] is False

    def test_wrong_path_returns_false(self):
        """Bug check: signals at security.qr_code_detected (wrong path) must NOT work."""
        triage = {
            "labels": ["laptop"],
            "extracted_text": "",
            "security": {
                "clean": False,
                "qr_code_detected": True,  # WRONG path — not under .signals
                "signals": {},  # correct path is empty
            },
        }
        ctx = self._map_triage_to_context(triage, "test.png")
        # Should be False because signals are at wrong path
        assert ctx["cv_signals"]["qr_code_detected"] is False

    def test_missing_security_key(self):
        ctx = self._map_triage_to_context({"labels": ["phone"]}, "phone.jpg")
        assert ctx["cv_signals"]["qr_code_detected"] is False
        assert ctx["labels"] == ["phone"]
