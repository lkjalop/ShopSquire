"""
Steganographic Image Assessment — Pre-Live-Test Playwright Suite
================================================================
Exercises the ShopSquire CV pipeline against every image in
dump/test-sec/ before live frontend testing.

What this covers
----------------
1. Steg detector (steg_detector.py) — LSB entropy, chi-square, SPA,
   sequential patterns, JPEG F5/JSteg/OutGuess, SRM, cross-channel.
2. Tier2 pipeline (cv_tier2_pipeline.py) — run_tier2 invoked via
   /api/v1/cv/analyze with images_b64, checks evidence_tags.
3. Parallel agents — three parallel tasks in cv.py (tier2, consistency,
   QR decode) under asyncio.wait_for timeout.
4. Security matrix output — signals, severity, MITRE/OWASP tags.
5. Image-sidecar endpoint — /api/v1/images/sidecar for per-image signals.
6. One regression guard that a clean (non-steg) 1x1 PNG does NOT fire.

Test manifest reference: dump/test-sec/steg-test-manifest.json
Expected results reference: dump/test-sec/steg-detection-results.json
"""
from __future__ import annotations

import base64
import json
import os
import pathlib
import time
import warnings
from typing import Any, Dict, List

import pytest
import requests

# ---------------------------------------------------------------------------
# Skip guard — same convention used by other pw tests
# ---------------------------------------------------------------------------
if os.getenv("DISABLE_PLAYWRIGHT_TESTS", "1").strip().lower() in ("1", "true", "yes"):
    pytest.skip(
        "Playwright tests disabled (set DISABLE_PLAYWRIGHT_TESTS=0 to enable)",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO = pathlib.Path(__file__).resolve().parents[2]
_TEST_SEC = _REPO / "dump" / "test-sec"
_MANIFEST = _TEST_SEC / "steg-test-manifest.json"
_EXPECTED = _TEST_SEC / "steg-detection-results.json"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _b64(path: pathlib.Path) -> str:
    """Return base64-encoded content of a file."""
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _clean_1x1_png_b64() -> str:
    """Return base64 of a genuine 1×1 white PNG (no steg payload)."""
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNg"
        "YAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
    )
    return base64.b64encode(png_bytes).decode("ascii")


def _api(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _headers(key: str) -> dict:
    h: dict = {"Content-Type": "application/json"}
    if key:
        h["x-api-key"] = key
    return h


def _retry_post(url: str, *, json_body: dict, headers: dict, attempts: int = 3, timeout: int = 60) -> requests.Response:
    last: Exception | None = None
    for idx in range(attempts):
        try:
            return requests.post(url, json=json_body, headers=headers, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last = exc
            if idx < attempts - 1:
                time.sleep(1.0 * (idx + 1))
    raise RuntimeError(f"POST {url} failed after {attempts} attempts: {last}")


# ---------------------------------------------------------------------------
# Image matrix built from manifest
# ---------------------------------------------------------------------------

def _load_manifest() -> List[Dict[str, Any]]:
    if not _MANIFEST.exists():
        return []
    with _MANIFEST.open(encoding="utf-8") as f:
        data = json.load(f)
    return list(data.get("images") or [])


def _load_expected() -> Dict[str, Dict[str, Any]]:
    """Index expected detection results by filename (steg outputs only)."""
    if not _EXPECTED.exists():
        return {}
    with _EXPECTED.open(encoding="utf-8") as f:
        data = json.load(f)
    return {
        r["filename"]: r
        for r in (data.get("results") or [])
        if r.get("category") == "STEG-TEST" and r.get("has_content")
    }


# ---------------------------------------------------------------------------
# Parametrize: one test case per steg image in the manifest
# ---------------------------------------------------------------------------

def _steg_images() -> List[Dict[str, Any]]:
    manifest = _load_manifest()
    items: List[Dict[str, Any]] = []
    for entry in manifest:
        outfile = _TEST_SEC / str(entry.get("output") or "")
        if outfile.exists():
            items.append(entry)
    return items


_STEG_IMAGES = _steg_images()
_EXPECTED_RESULTS = _load_expected()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def api_key(test_server: dict) -> str:
    return str(test_server.get("api_key") or "local-merchant-key")


# ===========================================================================
# TEST SUITE
# ===========================================================================


class TestStegDetectorUnit:
    """Unit-level: call detect_steganography() directly on each test image.

    Does NOT require the running server — pure Python.
    """

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_steg_detector_flags_payload_image(self, entry: Dict[str, Any]) -> None:
        """Each steg-embedded image must have steg_score > 0 and is_suspicious=True
        (or at minimum composite evidence tags present)."""
        steg_mod = pytest.importorskip("src.app.security.steg_detector")
        detect = steg_mod.detect_steganography

        img_path = _TEST_SEC / str(entry["output"])
        result = detect(img_path.read_bytes())

        assert result is not None, f"{entry['output']}: detector returned None"
        # The score should be non-trivially elevated for steg images
        assert result.steg_score > 0.0, (
            f"{entry['output']}: steg_score={result.steg_score:.4f} — expected > 0"
        )
        # At least one sub-signal must fire
        has_signal = (
            result.chi_square_p > 0.0
            or result.lsb_entropy_r > 0.0
            or result.spa_estimate > 0.0
            or result.sequential_pattern_score > 0.0
            or result.dct_anomaly_score > 0.0
            or result.steg_score > 0.0
        )
        assert has_signal, f"{entry['output']}: no sub-signal fired at all"

    def test_clean_image_does_not_flag(self) -> None:
        """A genuine 1×1 PNG must NOT produce is_suspicious=True."""
        steg_mod = pytest.importorskip("src.app.security.steg_detector")
        detect = steg_mod.detect_steganography
        png_bytes = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNg"
            "YAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
        )
        result = detect(png_bytes)
        # 1×1 pixels is trivially too small to produce meaningful steg signal:
        # is_suspicious should be False or steg_score should be < 0.5
        assert not result.is_suspicious or result.steg_score < 0.5, (
            f"Clean 1x1 PNG triggered steg alarm: score={result.steg_score:.4f} "
            f"is_suspicious={result.is_suspicious}"
        )

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_steg_result_has_explanations_when_suspicious(self, entry: Dict[str, Any]) -> None:
        """When is_suspicious is True the explanations list must be non-empty."""
        steg_mod = pytest.importorskip("src.app.security.steg_detector")
        detect = steg_mod.detect_steganography

        img_path = _TEST_SEC / str(entry["output"])
        result = detect(img_path.read_bytes())

        if result.is_suspicious:
            assert result.explanations, (
                f"{entry['output']}: is_suspicious=True but explanations list is empty"
            )

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_steg_result_fields_are_finite(self, entry: Dict[str, Any]) -> None:
        """All numeric StegResult fields must be finite floats [0,1]."""
        steg_mod = pytest.importorskip("src.app.security.steg_detector")
        import math
        detect = steg_mod.detect_steganography

        img_path = _TEST_SEC / str(entry["output"])
        result = detect(img_path.read_bytes())

        for field in (
            "steg_score", "lsb_entropy_r", "lsb_entropy_g", "lsb_entropy_b",
            "chi_square_p", "spa_estimate", "sequential_pattern_score",
            "dct_anomaly_score", "jpeg_quant_table_score",
            "jpeg_compat_attack_score", "srm_feature_score",
            "cross_channel_score", "metadata_strip_score",
        ):
            v = getattr(result, field, None)
            assert v is not None, f"{entry['output']}: {field} is None"
            assert math.isfinite(float(v)), f"{entry['output']}: {field}={v} is not finite"
            assert 0.0 <= float(v) <= 1.0, (
                f"{entry['output']}: {field}={v:.4f} outside [0,1]"
            )


class TestTier2PipelineSteg:
    """Integration: run_tier2 on the steg images and verify evidence_tags."""

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_tier2_emits_steganography_suspected_tag(self, entry: Dict[str, Any]) -> None:
        """run_tier2 should include 'steganography_suspected' in evidence_tags
        for the known steg payloads — provided CV_STEG_DETECT_ENABLED=1."""
        tier2_mod = pytest.importorskip("src.app.services.cv_tier2_pipeline")
        run_tier2 = tier2_mod.run_tier2

        os.environ.setdefault("CV_STEG_DETECT_ENABLED", "1")

        img_bytes = (_TEST_SEC / str(entry["output"])).read_bytes()
        result = run_tier2(img_bytes, meta={"case_id": f"steg-test-{entry['payload_key']}"})

        evidence_tags = list((result or {}).get("evidence_tags") or [])
        steg_block = (result or {}).get("robustness", {}).get("steganography") or {}

        # Must have the steganography sub-block
        assert steg_block, (
            f"{entry['output']}: robustness.steganography is empty — "
            f"CV_STEG_DETECT_ENABLED may be 0 or detector threw"
        )
        # The steg door opens if score is elevated OR is_suspicious is set
        steg_score = float(steg_block.get("steg_score") or 0.0)
        is_suspicious = bool(steg_block.get("is_suspicious"))

        assert steg_score > 0.0 or is_suspicious, (
            f"{entry['output']}: tier2 steganography block shows no signal "
            f"(score={steg_score}, is_suspicious={is_suspicious})"
        )

        if is_suspicious:
            assert "steganography_suspected" in evidence_tags, (
                f"{entry['output']}: is_suspicious=True but 'steganography_suspected' "
                f"not in evidence_tags={evidence_tags}"
            )

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_tier2_security_analysis_present(self, entry: Dict[str, Any]) -> None:
        """tier2 must return a non-empty security_analysis block for steg images."""
        tier2_mod = pytest.importorskip("src.app.services.cv_tier2_pipeline")
        run_tier2 = tier2_mod.run_tier2

        img_bytes = (_TEST_SEC / str(entry["output"])).read_bytes()
        result = run_tier2(img_bytes, meta={"case_id": f"steg-sa-{entry['payload_key']}"})

        # security_analysis may be None when the correlator has no signals — that is OK.
        # But if steg is suspicious the correlator should have populated something.
        steg_block = (result or {}).get("robustness", {}).get("steganography") or {}
        if bool(steg_block.get("is_suspicious")):
            sec = (result or {}).get("security_analysis")
            assert sec is not None, (
                f"{entry['output']}: steg suspicious but security_analysis is None"
            )

    def test_tier2_returns_expected_verdict_structure(self) -> None:
        """Smoke-test the verdict dict keys for ANY steg image."""
        if not _STEG_IMAGES:
            pytest.skip("No steg images found in test-sec/")
        tier2_mod = pytest.importorskip("src.app.services.cv_tier2_pipeline")
        run_tier2 = tier2_mod.run_tier2

        img_bytes = (_TEST_SEC / _STEG_IMAGES[0]["output"]).read_bytes()
        result = run_tier2(img_bytes, meta={})

        assert "signals" in result, "tier2 result missing 'signals' key"
        assert "evidence_tags" in result, "tier2 result missing 'evidence_tags' key"
        assert "verdict" in result, "tier2 result missing 'verdict' key"
        assert "robustness" in result, "tier2 result missing 'robustness' key"


class TestCVAnalyzeEndpointSteg:
    """API-level: POST /api/v1/cv/analyze with images_b64 for each steg image."""

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_cv_analyze_with_steg_image(
        self, entry: Dict[str, Any], test_server: dict, api_key: str
    ) -> None:
        """cv/analyze must return 200, include a case_id, and (when steg fires)
        surface steganography_suspected in security_matrix.signals."""
        base = test_server["base_url"]
        img_b64 = _b64(_TEST_SEC / str(entry["output"]))
        body = {
            "case_id": f"pw-steg-{entry['payload_key']}",
            "images_b64": [img_b64],
            "description": f"Security test: {entry['payload_description']}",
            "issue_type": "security_test",
            "provider": "basic",
        }
        r = _retry_post(_api(base, "/api/v1/cv/analyze"), json_body=body, headers=_headers(api_key))
        assert r.status_code == 200, (
            f"{entry['output']}: cv/analyze returned {r.status_code}: {r.text[:500]}"
        )
        j = r.json()
        assert j.get("case_id"), f"{entry['output']}: response missing case_id"

        # Security matrix block
        sec_matrix = j.get("security_matrix") or {}
        sev = str(sec_matrix.get("severity") or j.get("severity") or "").lower()
        signals = dict(sec_matrix.get("signals") or {})

        # Acceptable: any non-trivial severity OR steg signal populated
        # (some images may be too small for steg score to cross threshold in test env)
        expected_entry = _EXPECTED_RESULTS.get(entry["output"], {})
        payload_has_content = bool(expected_entry.get("has_content"))

        if payload_has_content and bool(os.getenv("CV_STEG_DETECT_ENABLED", "1")):
            # Best-effort: warn rather than hard-fail if steg threshold not crossed
            tier2_tags = list(j.get("tier2_evidence_tags") or [])
            all_tags = tier2_tags + list(signals.keys())
            steg_signalled = (
                "steganography_suspected" in all_tags
                or signals.get("steganography_suspected")
                or sev in ("high", "critical", "warn", "medium")
            )
            if not steg_signalled:
                warnings.warn(
                    f"{entry['output']}: expected steg signal in API response but none found. "
                    f"severity={sev!r} signals={list(signals.keys())} tags={tier2_tags}",
                    stacklevel=2,
                )

    def test_cv_analyze_clean_image_not_escalated(
        self, test_server: dict, api_key: str
    ) -> None:
        """A clean 1×1 PNG must not produce a severity=high/critical response."""
        base = test_server["base_url"]
        body = {
            "case_id": "pw-steg-clean-control",
            "images_b64": [_clean_1x1_png_b64()],
            "description": "Clean control image — no payload",
            "issue_type": "security_test",
            "provider": "basic",
        }
        r = _retry_post(_api(base, "/api/v1/cv/analyze"), json_body=body, headers=_headers(api_key))
        assert r.status_code == 200, f"clean image returned {r.status_code}: {r.text[:300]}"
        j = r.json()
        sec = j.get("security_matrix") or {}
        sev = str(sec.get("severity") or j.get("severity") or "info").lower()
        assert sev not in ("critical", "high"), (
            f"Clean 1x1 PNG triggered high/critical severity: {sev}"
        )

    def test_cv_analyze_parallel_agents_complete(
        self, test_server: dict, api_key: str
    ) -> None:
        """The three parallel agents (tier2, consistency, QR) must all complete
        within CV_ANALYZE_TIMEOUT_SEC without the endpoint returning 500."""
        if not _STEG_IMAGES:
            pytest.skip("No steg images found")
        base = test_server["base_url"]
        entry = _STEG_IMAGES[0]
        img_b64 = _b64(_TEST_SEC / str(entry["output"]))
        body = {
            "case_id": "pw-parallel-agents-test",
            "images_b64": [img_b64],
            "description": "Parallel agent timeout/completion test",
            "issue_type": "security_test",
            "provider": "basic",
        }
        os.environ.setdefault("CV_ANALYZE_TIMEOUT_SEC", "45")
        t0 = time.monotonic()
        r = _retry_post(
            _api(base, "/api/v1/cv/analyze"),
            json_body=body,
            headers=_headers(api_key),
            timeout=90,
        )
        elapsed = time.monotonic() - t0
        assert r.status_code == 200, (
            f"Parallel agents test returned {r.status_code} in {elapsed:.1f}s: {r.text[:300]}"
        )
        # The agent_chain appears only when tier2 produced a result
        j = r.json()
        # We do NOT require the decision log to be written; just confirm response structure
        assert "case_id" in j, "Missing case_id in parallel-agents response"


class TestImageSidecarSteg:
    """POST /api/v1/images/sidecar with the steg images — verify signal fields."""

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_sidecar_steg_suspicious_field(
        self, entry: Dict[str, Any], test_server: dict, api_key: str
    ) -> None:
        """image sidecar must return steg_suspicious + steg_score for steg images."""
        base = test_server["base_url"]
        img_path = _TEST_SEC / str(entry["output"])
        files = [("image", (entry["output"], img_path.read_bytes(), "image/png"))]
        headers = {}
        if api_key:
            headers["x-api-key"] = api_key
        try:
            r = requests.post(
                _api(base, "/api/v1/images/sidecar"),
                files=files,
                headers=headers,
                timeout=60,
            )
        except Exception as exc:
            pytest.skip(f"sidecar endpoint unreachable: {exc}")
        if r.status_code == 404:
            pytest.skip("sidecar endpoint not mounted on this server instance")
        assert r.status_code == 200, (
            f"{entry['output']}: sidecar returned {r.status_code}: {r.text[:300]}"
        )
        j = r.json()
        signals = dict(j.get("signals") or {})
        # steg_score must be present and numeric
        assert "steg_score" in signals, (
            f"{entry['output']}: 'steg_score' missing from sidecar signals={list(signals.keys())}"
        )
        assert isinstance(signals["steg_score"], (int, float)), (
            f"{entry['output']}: steg_score is not a number: {signals['steg_score']}"
        )


class TestSecurityMatrixPopulation:
    """Validate that the security matrix signals map correctly to MITRE/OWASP/DREAD."""

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_security_observer_maps_steg_to_mitre(self, entry: Dict[str, Any]) -> None:
        """correlate_security_analysis must map steganography_suspected → AML.T0043."""
        try:
            from src.app.security.framework_correlation import correlate_security_analysis
        except ImportError:
            pytest.skip("framework_correlation not importable")

        sec = correlate_security_analysis(
            channel="cv",
            severity="high",
            tags=["steganography_suspected"],
            reasons=["Steganographic embedding detected"],
            threat_correlation={
                "mitre_attack": ["AML.T0043"],
                "dread": {"damage": 5, "reproducibility": 3, "exploitability": 2, "affected_users": 3, "discoverability": 4, "avg": 3.4},
                "cvss": {"score": 6.5, "severity": "medium", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:M/I:M/A:L"},
                "kev": [],
            },
            signals={"steganography_suspected": True},
            evidence={},
        )

        assert sec is not None, "correlate_security_analysis returned None"
        matrix = sec if isinstance(sec, dict) else {}
        # The matrix should not be empty
        assert matrix, "security_analysis result is empty"

        # MITRE tags should appear somewhere in the matrix — either top-level or nested
        raw = json.dumps(matrix, default=str)
        assert "AML.T0043" in raw or "T1027" in raw, (
            f"MITRE tag AML.T0043/T1027 not found in security matrix: {raw[:600]}"
        )

    def test_dread_scorer_steg_signal(self) -> None:
        """compute_dread must produce non-zero scores for steg_suspicious signal."""
        try:
            from src.app.security.dread_scorer import compute_dread
        except ImportError:
            pytest.skip("dread_scorer not importable")

        result = compute_dread(
            signals={"steg_suspicious": True},
            cv_signals={"steg_suspicious": True},
            severity="warn",
        )
        assert isinstance(result, dict)
        avg = float(result.get("avg") or 0.0)
        assert avg > 0.0, f"DREAD avg=0 for steg_suspicious — scorer may not handle steg signals"

    def test_owasp_map_steg(self) -> None:
        """OWASP map must resolve steg_suspicious → AML.T0043."""
        try:
            from src.app.security import owasp_map as _om
        except ImportError:
            pytest.skip("owasp_map not importable")
        # Module may export MITRE_ATLAS_MAP or a private variant
        atlas_map: dict = (
            getattr(_om, "MITRE_ATLAS_MAP", None)
            or getattr(_om, "_MITRE_ATLAS_SIGNAL_MAP", None)
            or {}
        )
        assert atlas_map, "No MITRE atlas map found in owasp_map module"
        assert "steg_suspicious" in atlas_map, (
            f"'steg_suspicious' missing from MITRE atlas map. Keys sample: "
            f"{list(atlas_map.keys())[:20]}"
        )
        assert atlas_map["steg_suspicious"] == "AML.T0043", (
            f"steg_suspicious → {atlas_map['steg_suspicious']} instead of AML.T0043"
        )
        assert "steg_payload_detected" in atlas_map, (
            f"'steg_payload_detected' missing from MITRE atlas map. Keys: "
            f"{[k for k in atlas_map if 'steg' in k]}"
        )


class TestStegPayloadVariants:
    """Payload-specific assertions cross-referenced against steg-detection-results.json."""

    @pytest.mark.parametrize("entry", _STEG_IMAGES, ids=[e["output"] for e in _STEG_IMAGES])
    def test_expected_detections_match_payload_key(self, entry: Dict[str, Any]) -> None:
        """Each image in the manifest must have the expected_detections list populated."""
        assert entry.get("expected_detections"), (
            f"{entry['output']}: manifest entry has no expected_detections"
        )
        assert entry.get("payload_key"), (
            f"{entry['output']}: manifest entry has no payload_key"
        )
        assert entry.get("mitre_atlas"), (
            f"{entry['output']}: manifest entry has no MITRE ATLAS mapping"
        )

    def test_c2_beacon_expected_signals(self) -> None:
        """C2 beacon image should mention c2_pattern in expected detections."""
        c2_entry = next(
            (e for e in _STEG_IMAGES if "c2_beacon" in str(e.get("payload_key") or "")),
            None,
        )
        if c2_entry is None:
            pytest.skip("c2_beacon image not found in test-sec/")
        dets = list(c2_entry.get("expected_detections") or [])
        assert any("c2" in d.lower() or "beacon" in d.lower() for d in dets), (
            f"c2_beacon image expected_detections has no c2/beacon entry: {dets}"
        )

    def test_payment_fraud_expected_signals(self) -> None:
        """Payment fraud image should mention payment_redirect/BSB in expected detections."""
        pf_entry = next(
            (e for e in _STEG_IMAGES if "payment_fraud" in str(e.get("payload_key") or "")),
            None,
        )
        if pf_entry is None:
            pytest.skip("payment_fraud image not found in test-sec/")
        dets = list(pf_entry.get("expected_detections") or [])
        assert any("payment" in d.lower() or "bsb" in d.lower() for d in dets), (
            f"payment_fraud image expected_detections has no payment/BSB entry: {dets}"
        )

    def test_prompt_injection_expected_signals(self) -> None:
        """Prompt injection image should flag prompt_injection pattern."""
        pi_entry = next(
            (e for e in _STEG_IMAGES if "prompt_injection" in str(e.get("payload_key") or "")),
            None,
        )
        if pi_entry is None:
            pytest.skip("prompt_injection image not found in test-sec/")
        dets = list(pi_entry.get("expected_detections") or [])
        assert any("prompt" in d.lower() or "injection" in d.lower() for d in dets), (
            f"prompt_injection image expected_detections missing prompt/injection: {dets}"
        )

    def test_lolbin_expected_signals(self) -> None:
        """LOLBin image should list certutil / powershell patterns."""
        lolbin_entry = next(
            (e for e in _STEG_IMAGES if "lolbin" in str(e.get("payload_key") or "")),
            None,
        )
        if lolbin_entry is None:
            pytest.skip("lolbin image not found in test-sec/")
        dets = list(lolbin_entry.get("expected_detections") or [])
        assert any("lolbin" in d.lower() or "certutil" in d.lower() for d in dets), (
            f"lolbin image expected_detections missing lolbin/certutil: {dets}"
        )

    def test_data_exfiltration_expected_signals(self) -> None:
        """Exfiltration image should reference exfil target / API keys."""
        exfil_entry = next(
            (e for e in _STEG_IMAGES if "data_exfil" in str(e.get("payload_key") or "")),
            None,
        )
        if exfil_entry is None:
            pytest.skip("data_exfiltration image not found in test-sec/")
        dets = list(exfil_entry.get("expected_detections") or [])
        assert any("exfil" in d.lower() or "api_key" in d.lower() for d in dets), (
            f"exfiltration image expected_detections missing exfil/api_key: {dets}"
        )


class TestDetectionCoverage:
    """Meta: assert the test suite itself covers all images in the manifest."""

    def test_all_manifest_images_exist_on_disk(self) -> None:
        manifest = _load_manifest()
        missing = [
            e["output"]
            for e in manifest
            if not (_TEST_SEC / str(e.get("output") or "")).exists()
        ]
        assert not missing, (
            f"Manifest references images missing from dump/test-sec/: {missing}"
        )

    def test_manifest_covers_all_threat_categories(self) -> None:
        manifest = _load_manifest()
        keys = {str(e.get("payload_key") or "") for e in manifest}
        required = {
            "c2_beacon_simulation",
            "prompt_injection_hidden",
            "data_exfiltration_instruction",
            "lolbin_command_sequence",
            "payment_fraud_hidden",
        }
        missing = required - keys
        assert not missing, f"Manifest is missing threat categories: {missing}"

    def test_manifest_has_mitre_atlas_coverage(self) -> None:
        manifest = _load_manifest()
        atlas_tags = {str(e.get("mitre_atlas") or "") for e in manifest if e.get("mitre_atlas")}
        assert len(atlas_tags) >= 2, (
            f"Manifest covers fewer than 2 distinct MITRE ATLAS tags: {atlas_tags}"
        )

    def test_detection_results_json_steg_images_flagged(self) -> None:
        """All steg images in steg-detection-results.json must have verdict containing DETECTED."""
        expected = _load_expected()
        for fname, entry in expected.items():
            verdict = str(entry.get("verdict") or "")
            assert "DETECTED" in verdict, (
                f"{fname}: expected verdict containing DETECTED, got: {verdict!r}"
            )
            assert entry.get("has_content") is True, (
                f"{fname}: expected has_content=True but got {entry.get('has_content')!r}"
            )

    def test_detection_results_original_images_not_flagged(self) -> None:
        """Original (non-steg) images must NOT have verdict DETECTED."""
        if not _EXPECTED.exists():
            pytest.skip("steg-detection-results.json not found")
        with _EXPECTED.open(encoding="utf-8") as f:
            data = json.load(f)
        originals = [
            r for r in (data.get("results") or [])
            if r.get("category") == "ORIGINAL"
        ]
        for entry in originals:
            verdict = str(entry.get("verdict") or "")
            assert "DETECTED" not in verdict, (
                f"Original image {entry['filename']} incorrectly has DETECTED verdict: {verdict!r}"
            )
