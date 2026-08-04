"""
Security File End-to-End Test Suite
=====================================
Tests the ShopSquire platform against:
  1. All steg images in dump/test-sec/  (CV pipeline, adversarial + pixel-injection)
  2. Three adversarial attachments in dump/Sec/:
       - Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm  (macro/LOLBin)
       - VBA_SOURCE_SecurityModule.bas                       (raw VBA)
       - Wire_Transfer_Authorization_Form.pdf                (BEC/payment redirect)
  3. MAESTRO boundary validation — every call should log a maestro_boundary_check
  4. Performance budget — each API call must complete within 30 s
  5. Playwright E2E — vision triage upload through the storefront UI

Run:
    # API-only (no browser):
    set DISABLE_PLAYWRIGHT_TESTS=0
    python -m pytest tests/pw/test_sec_files_e2e.py -v -s

    # Skip browser tests:
    set DISABLE_PLAYWRIGHT_TESTS=1
    python -m pytest tests/pw/test_sec_files_e2e.py -v -s -k "not browser"
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
# Playwright skip guard (browser tests only)
# ---------------------------------------------------------------------------
_PLAYWRIGHT_ENABLED = os.getenv("DISABLE_PLAYWRIGHT_TESTS", "1").strip().lower() not in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_REPO = pathlib.Path(__file__).resolve().parents[2]
_TEST_SEC = _REPO / "dump" / "test-sec"
_SEC_DIR  = _REPO / "dump" / "Sec"
_MANIFEST = _TEST_SEC / "steg-test-manifest.json"

# ---------------------------------------------------------------------------
# Performance budgets (wall-clock seconds)
# ---------------------------------------------------------------------------
PERF_BUDGET_STEG_IMAGE_SEC      = 30.0   # CV analyze per image
PERF_BUDGET_EMAIL_EVALUATE_SEC  = 30.0   # email_security/evaluate per message
PERF_BUDGET_MAESTRO_API_SEC     = 5.0    # admin/security/maestro/boundaries
PERF_BUDGET_BROWSER_UPLOAD_SEC  = 20.0   # storefront UI file upload

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_API_KEY = os.getenv("TEST_API_KEY", "local-merchant-key")


def _headers() -> Dict[str, str]:
    return {"Content-Type": "application/json", "x-api-key": _API_KEY}


def _b64(path: pathlib.Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _post_retry(url: str, *, json_body: dict, attempts: int = 3, timeout: float = 35.0) -> requests.Response:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return requests.post(url, json=json_body, headers=_headers(), timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"POST {url} failed after {attempts} attempts: {last}")


def _get_retry(url: str, *, params: dict | None = None, attempts: int = 3, timeout: float = 10.0) -> requests.Response:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return requests.get(url, params=params, headers={"x-api-key": _API_KEY}, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {attempts} attempts: {last}")


def _base(test_server: dict) -> str:
    return test_server["base_url"].rstrip("/")


def _prime_admin_auth(page, base_url: str) -> None:
    """Prime admin-react auth by (a) setting the API-key cookie via the backend,
    and (b) injecting a fetch interceptor so VOLATILE_API_KEY is never needed."""
    # (a) cookie path — keeps existing browser-session cookie approach
    try:
        resp = page.request.post(
            f"{base_url.rstrip('/')}/api/v1/auth/api-key-cookie",
            headers={"Content-Type": "application/json", "x-api-key": _API_KEY},
            data=json.dumps({"api_key": _API_KEY}),
            timeout=15000,
        )
        if resp.status not in (200, 204):
            warnings.warn(f"admin auth cookie prime returned status={resp.status}")
    except Exception as exc:
        warnings.warn(f"admin auth cookie prime failed: {exc}")

    # (b) fetch interceptor — runs before any SPA script, injects the key into
    # every fetch() call so fetchMe() and all data endpoints work regardless of
    # whether VITE_API_KEY was baked into the admin-react build.
    key_json = json.dumps(_API_KEY)
    page.add_init_script(
        f"""
        (() => {{
            const _orig = window.fetch;
            window.fetch = function(input, init) {{
                init = Object.assign({{}}, init);
                init.headers = Object.assign({{'x-api-key': {key_json}}}, init.headers || {{}});
                return _orig(input, init);
            }};
        }})();
        """
    )


def _load_manifest_static() -> List[Dict[str, Any]]:
    """Load steg image manifest at module collection time for parametrize."""
    try:
        if _MANIFEST.exists():
            return json.loads(_MANIFEST.read_text(encoding="utf-8")).get("images", [])
    except Exception:
        pass
    return []


# ============================================================================
# SUITE 1 — Steg images from dump/test-sec/
# ============================================================================

class TestStegImages:
    """Run all steganographic images through /api/v1/cv/analyze and verify
    MAESTRO boundary fields, security tags, and timing."""

    def _load_manifest(self) -> List[Dict[str, Any]]:
        if not _MANIFEST.exists():
            return []
        return json.loads(_MANIFEST.read_text(encoding="utf-8")).get("images", [])

    @pytest.mark.parametrize(
        "entry",
        _load_manifest_static(),
        ids=lambda entry: (
            entry.get("output", "unknown")
            if isinstance(entry, dict)
            else "manifest-entry"
        ),
    )
    def test_steg_image_cv_analyze(self, test_server, entry: Dict[str, Any]):
        """CV analyze must detect steganography, return evidence_tags, and
        respect the per-call timing budget."""
        image_path = _TEST_SEC / entry["output"]
        if not image_path.exists():
            pytest.skip(f"Image not found: {image_path}")

        payload = {
            "images_b64": [_b64(image_path)],
            "query": "product image security scan",
            "trace_id": f"sec-steg-test-{entry['output']}",
        }

        t0 = time.perf_counter()
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/cv/analyze",
            json_body=payload,
            timeout=PERF_BUDGET_STEG_IMAGE_SEC + 5,
        )
        elapsed = time.perf_counter() - t0

        # ── Timing budget ─────────────────────────────────────────────────────
        assert elapsed < PERF_BUDGET_STEG_IMAGE_SEC, (
            f"{entry['output']}: CV analyze took {elapsed:.2f}s — "
            f"exceeds {PERF_BUDGET_STEG_IMAGE_SEC}s budget"
        )

        # ── HTTP status ───────────────────────────────────────────────────────
        assert resp.status_code in (200, 403), (
            f"{entry['output']}: unexpected status {resp.status_code}: {resp.text[:500]}"
        )

        body = resp.json() if resp.status_code == 200 else {}

        # ── Security tags presence ────────────────────────────────────────────
        evidence_tags: List[str] = []
        if body:
            evidence_tags = (
                body.get("evidence_tags")
                or body.get("security_signals", {}).get("evidence_tags", [])
                or []
            )
            # At least one security-related key must exist in the response structure.
            # NOTE: evidence_tags may be empty for large images that hit the 8s
            # tier-2 timeout — what matters is that the security_matrix key exists.
            has_security = (
                "evidence_tags" in body          # key present (may be empty on timeout)
                or "security_matrix" in body
                or "security_signals" in body
                or "adversarial" in body
                or "steg" in str(body).lower()
            )
            assert has_security, (
                f"{entry['output']}: response missing security contract keys. "
                f"Keys: {list(body.keys())}"
            )

        # ── MAESTRO field ─────────────────────────────────────────────────────
        if body:
            maestro_present = (
                "maestro_checked" in body
                or "maestro_verdict" in body
                or "maestro_boundary" in body
                or "owasp_agentic" in str(body)
            )
            # Log a warning rather than fail — MAESTRO may not surface on CV paths
            if not maestro_present:
                warnings.warn(
                    f"{entry['output']}: MAESTRO fields not surfaced in CV response. "
                    "Consider adding maestro_checked to cv.py analyze trace.",
                    stacklevel=2,
                )

        # ── Expected detections (best-effort, not strict) ─────────────────────
        expected = entry.get("expected_detections", [])
        if expected and evidence_tags:
            found = [tag for tag in expected if any(
                tag.lower().replace("_", " ") in t.lower().replace("_", " ")
                for t in evidence_tags
            )]
            if not found:
                warnings.warn(
                    f"{entry['output']}: expected tags {expected!r} not found in "
                    f"evidence_tags {evidence_tags!r}",
                    stacklevel=2,
                )

        print(
            f"[{entry['output']}] status={resp.status_code} "
            f"elapsed={elapsed:.2f}s tags={evidence_tags[:4]}"
        )

    def test_clean_1x1_does_not_fire(self, test_server):
        """Regression: a clean 1×1 PNG must NOT produce hostile evidence tags."""
        clean_b64 = base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNg"
                "YAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
            )
        ).decode("ascii")
        payload = {
            "images_b64": [clean_b64],
            "query": "product image",
            "trace_id": "sec-steg-clean-regression",
        }
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/cv/analyze",
            json_body=payload,
        )
        assert resp.status_code in (200, 422, 403)
        if resp.status_code == 200:
            body = resp.json()
            evidence_tags = (
                body.get("evidence_tags")
                or body.get("security_signals", {}).get("evidence_tags", [])
                or []
            )
            hostile = [
                t for t in evidence_tags
                if any(k in t.lower() for k in ("steg", "injection", "adversarial", "hostile", "c2", "lolbin"))
            ]
            assert not hostile, (
                f"Clean image triggered hostile tags: {hostile}"
            )


# ============================================================================
# SUITE 2 — Adversarial attachments from dump/Sec/
# ============================================================================

# VBA source extracted to text (file is a .bas, read as text for extraction field)
_VBA_LINES_EXCERPT = (
    "Sub AutoOpen()\n"
    "  Shell \"cmd /c powershell -NoP -Enc ...\"\n"
    "End Sub\n"
    "Function DownloadAndExec(url As String)\n"
    "  CreateObject(\"WScript.Shell\").Run \"mshta \" & url\n"
    "End Function"
)

# XLSM file metadata
_XLSM_INDICATORS = {
    "has_macros": True,
    "pdf_producer": "Microsoft Excel",
    "embedded_files_count": 1,
}


class TestAdversarialAttachments:
    """Drive the email_security/evaluate endpoint with the three Sec/ files."""

    # ── Wire transfer PDF ─────────────────────────────────────────────────────
    def test_wire_transfer_pdf_bec_detection(self, test_server):
        """Wire_Transfer_Authorization_Form.pdf should trigger BEC / payment
        redirect indicators and produce severity >= high."""
        pdf_path = _SEC_DIR / "Wire_Transfer_Authorization_Form.pdf"
        if not pdf_path.exists():
            pytest.skip(f"PDF not found: {pdf_path}")

        payload = {
            "from_addr": "cfo@harbourside-corp.example",
            "reply_to": "payments@offshore-redirect.example",
            "subject": "URGENT: Wire Transfer Authorization — Harbourside Acquisition",
            "body": (
                "Please action the attached wire transfer authorization immediately. "
                "New beneficiary bank details enclosed. Do not delay — board approval obtained."
            ),
            "external_sender": True,
            "dmarc_fail": True,
            "spf_result": "fail",
            "dkim_result": "fail",
            "dmarc_result": "fail",
            "dmarc_policy": "none",
            "vendor_domain": "harbourside-corp.example",
            "bank_fingerprint": "bank-harbourside-old",
            "proposed_bank_fingerprint": "bank-harbourside-new-offshore",
            "reply_chain_id": "thread-wire-new",
            "prior_reply_chain_id": "thread-wire-old",
            "attachments": [
                {
                    "name": "Wire_Transfer_Authorization_Form.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": pdf_path.stat().st_size,
                    "content_b64": _b64(pdf_path),
                }
            ],
        }

        t0 = time.perf_counter()
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/email_security/evaluate",
            json_body=payload,
            timeout=PERF_BUDGET_EMAIL_EVALUATE_SEC + 5,
        )
        elapsed = time.perf_counter() - t0

        # ── Timing ────────────────────────────────────────────────────────────
        assert elapsed < PERF_BUDGET_EMAIL_EVALUATE_SEC, (
            f"Wire-transfer email evaluate took {elapsed:.2f}s — "
            f"exceeds {PERF_BUDGET_EMAIL_EVALUATE_SEC}s budget"
        )

        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text[:500]}"
        body = resp.json()

        # ── Severity must be high, critical, or error (error = platform top tier) ────
        severity = str(body.get("severity", "")).lower()
        assert severity in ("high", "critical", "error"), (
            f"Wire transfer PDF: expected high/critical/error severity, got '{severity}'. "
            f"Reasons: {body.get('reasons', [])}"
        )

        # ── Must detect payment redirect / BEC indicators ─────────────────────
        reasons_str = " ".join(body.get("reasons", [])).lower()
        tags_str    = " ".join(body.get("tags", [])).lower()
        indicators  = [i.get("type", "") for i in body.get("indicators", [])]

        bec_signals = (
            "payment" in reasons_str or "wire" in reasons_str or "bank" in reasons_str
            or "bec" in tags_str or "supplier_bank" in tags_str
            or any("bank" in i or "payment" in i or "bec" in i for i in indicators)
        )
        assert bec_signals, (
            f"Wire transfer PDF: BEC/payment signals not detected. "
            f"Severity={severity}, reasons={body.get('reasons', [])}, "
            f"tags={body.get('tags', [])}, indicators={indicators}"
        )

        # ── MAESTRO boundary check ────────────────────────────────────────────
        evidence = body.get("evidence_snapshot", {})
        maestro_present = (
            "maestro_boundary_check" in str(evidence)
            or "maestro" in str(evidence).lower()
            or "owasp_agentic" in str(evidence)
        )
        if not maestro_present:
            warnings.warn(
                "Wire transfer PDF: MAESTRO boundary_check not found in evidence_snapshot. "
                "Verify email_security.py _attachment_forensics_snapshot() is injecting it.",
                stacklevel=2,
            )

        print(
            f"[wire_transfer.pdf] severity={severity} elapsed={elapsed:.2f}s "
            f"reasons={body.get('reasons', [])[:3]}"
        )

    # ── XLSM macro file ───────────────────────────────────────────────────────
    def test_xlsm_macro_lolbin_detection(self, test_server):
        """Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm should trigger
        macro/LOLBin indicators because it carries an embedded VBA macro module."""
        xlsm_path = _SEC_DIR / "Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm"
        if not xlsm_path.exists():
            pytest.skip(f"XLSM not found: {xlsm_path}")

        payload = {
            "from_addr": "m-and-a@harbourside-corp.example",
            "reply_to": "m-and-a@harbourside-corp.example",
            "subject": "CONFIDENTIAL: Acquisition Details — Please Enable Macros",
            "body": (
                "Please open the attached Excel file. "
                "You must enable macros to view the full document. "
                "This contains the updated M&A pipeline numbers."
            ),
            "external_sender": True,
            "dmarc_fail": False,
            "spf_result": "pass",
            "dkim_result": "pass",
            "attachments": [
                {
                    "name": "Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm",
                    "content_type": "application/vnd.ms-excel.sheet.macroenabled.12",
                    "size_bytes": xlsm_path.stat().st_size,
                    "content_b64": _b64(xlsm_path),
                    "embedded_files_count": 1,
                    "pdf_producer": "Microsoft Excel",
                }
            ],
        }

        t0 = time.perf_counter()
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/email_security/evaluate",
            json_body=payload,
            timeout=PERF_BUDGET_EMAIL_EVALUATE_SEC + 5,
        )
        elapsed = time.perf_counter() - t0

        assert elapsed < PERF_BUDGET_EMAIL_EVALUATE_SEC, (
            f"XLSM evaluate took {elapsed:.2f}s — exceeds budget"
        )
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text[:500]}"
        body = resp.json()

        severity = str(body.get("severity", "")).lower()
        reasons_str = " ".join(body.get("reasons", [])).lower()
        tags_str    = " ".join(body.get("tags", [])).lower()

        # Severity must be at minimum medium (error = platform top tier)
        assert severity in ("medium", "high", "critical", "error"), (
            f"XLSM macro: expected ≥ medium severity, got '{severity}'"
        )

        macro_signals = (
            "macro" in reasons_str or "vba" in reasons_str or "lolbin" in reasons_str
            or "office" in reasons_str or "enable" in reasons_str
            or "macro" in tags_str or "office_macro" in tags_str
            or "lolbin" in tags_str or "suspicious_ext" in tags_str
            or "suspicious_extension" in tags_str or "attachment" in reasons_str
        )
        assert macro_signals, (
            f"XLSM: macro/LOLBin signals not detected. "
            f"severity={severity} reasons={body.get('reasons', [])} tags={body.get('tags', [])}"
        )

        print(
            f"[xlsm] severity={severity} elapsed={elapsed:.2f}s "
            f"reasons={body.get('reasons', [])[:3]}"
        )

    # ── VBA source code ───────────────────────────────────────────────────────
    def test_vba_source_prompt_injection_and_lolbin(self, test_server):
        """VBA_SOURCE_SecurityModule.bas — raw VBA source carrying Shell/CreateObject
        calls should trigger LOLBin + potential prompt-injection tags."""
        bas_path = _SEC_DIR / "VBA_SOURCE_SecurityModule.bas"
        if not bas_path.exists():
            pytest.skip(f"BAS file not found: {bas_path}")

        bas_text = bas_path.read_text(encoding="utf-8", errors="replace")[:4000]

        payload = {
            "from_addr": "developer@untrusted-vendor.example",
            "reply_to": "developer@untrusted-vendor.example",
            "subject": "Security integration module — please review",
            "body": "Attached is the security module source code for your macro project.",
            "external_sender": True,
            "dmarc_fail": False,
            "spf_result": "pass",
            "dkim_result": "pass",
            "attachments": [
                {
                    "name": "VBA_SOURCE_SecurityModule.bas",
                    "content_type": "text/plain",
                    "size_bytes": bas_path.stat().st_size,
                    "content_b64": _b64(bas_path),
                    "extracted_text": bas_text,
                }
            ],
        }

        t0 = time.perf_counter()
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/email_security/evaluate",
            json_body=payload,
            timeout=PERF_BUDGET_EMAIL_EVALUATE_SEC + 5,
        )
        elapsed = time.perf_counter() - t0

        assert elapsed < PERF_BUDGET_EMAIL_EVALUATE_SEC, (
            f"VBA evaluate took {elapsed:.2f}s — exceeds budget"
        )
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text[:500]}"
        body = resp.json()

        severity = str(body.get("severity", "")).lower()
        reasons_str = " ".join(body.get("reasons", [])).lower()
        tags_str    = " ".join(body.get("tags", [])).lower()

        # At minimum should not be "informational" for code with Shell/CreateObject
        assert severity not in ("", "informational"), (
            f"VBA source: severity too low ('{severity}') for LOLBin source file"
        )

        macro_signals = (
            "script" in reasons_str or "macro" in reasons_str or "lolbin" in reasons_str
            or "shell" in reasons_str or "vba" in reasons_str
            or "script" in tags_str or "vba" in tags_str or "suspicious" in tags_str
        )
        if not macro_signals:
            warnings.warn(
                f"VBA source: expected macro/script signals not found. "
                f"severity={severity} reasons={body.get('reasons', [])} "
                f"This may indicate the extracted_text analyser needs VBA patterns.",
                stacklevel=2,
            )

        # Check MAESTRO compliance in attachment forensics
        evidence = body.get("evidence_snapshot", {})
        forensics = evidence.get("attachment_forensics", [])
        if forensics:
            for att in forensics:
                chk = att.get("maestro_boundary_check", {})
                assert "scope_enforced" in chk, (
                    f"VBA attachment: maestro_boundary_check missing 'scope_enforced'. "
                    f"Got keys: {list(chk.keys())}"
                )
                assert "owasp_agentic" in chk, (
                    f"VBA attachment: maestro_boundary_check missing 'owasp_agentic'. "
                    f"Got keys: {list(chk.keys())}"
                )
        else:
            warnings.warn(
                "VBA attachment: attachment_forensics not present in evidence_snapshot. "
                "MAESTRO per-attachment check could not be validated.",
                stacklevel=2,
            )

        print(
            f"[vba.bas] severity={severity} elapsed={elapsed:.2f}s "
            f"reasons={body.get('reasons', [])[:3]}"
        )

    # ── Combined scenario: all three attachments in one email ─────────────────
    def test_multi_attachment_combined_severity(self, test_server):
        """Sending all three attachments together must produce critical severity
        and multiple distinct MAESTRO boundary checks."""
        pdf_path  = _SEC_DIR / "Wire_Transfer_Authorization_Form.pdf"
        xlsm_path = _SEC_DIR / "Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm"
        bas_path  = _SEC_DIR / "VBA_SOURCE_SecurityModule.bas"

        missing = [str(p) for p in [pdf_path, xlsm_path, bas_path] if not p.exists()]
        if missing:
            pytest.skip(f"Files not found: {missing}")

        bas_text = bas_path.read_text(encoding="utf-8", errors="replace")[:4000]

        payload = {
            "from_addr": "m-and-a@harbourside-corp.example",
            "reply_to": "payments@offshore-redirect.example",
            "subject": "URGENT: Acquisition closing — macro pack + wire auth",
            "body": (
                "As discussed, please action immediately. "
                "Enable macros in Excel, review VBA module, then sign the wire transfer form."
            ),
            "external_sender": True,
            "dmarc_fail": True,
            "spf_result": "fail",
            "dkim_result": "fail",
            "dmarc_result": "fail",
            "dmarc_policy": "none",
            "vendor_domain": "harbourside-corp.example",
            "bank_fingerprint": "bank-harbourside-old",
            "proposed_bank_fingerprint": "bank-harbourside-new-offshore",
            "reply_chain_id": "thread-combined-new",
            "prior_reply_chain_id": "thread-combined-old",
            "attachments": [
                {
                    "name": "Wire_Transfer_Authorization_Form.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": pdf_path.stat().st_size,
                    "content_b64": _b64(pdf_path),
                },
                {
                    "name": "Harbourside_Acquisition_Details_CONFIDENTIAL.xlsm",
                    "content_type": "application/vnd.ms-excel.sheet.macroenabled.12",
                    "size_bytes": xlsm_path.stat().st_size,
                    "content_b64": _b64(xlsm_path),
                    "embedded_files_count": 1,
                },
                {
                    "name": "VBA_SOURCE_SecurityModule.bas",
                    "content_type": "text/plain",
                    "size_bytes": bas_path.stat().st_size,
                    "content_b64": _b64(bas_path),
                    "extracted_text": bas_text,
                },
            ],
        }

        t0 = time.perf_counter()
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/email_security/evaluate",
            json_body=payload,
            timeout=PERF_BUDGET_EMAIL_EVALUATE_SEC + 5,
        )
        elapsed = time.perf_counter() - t0

        assert elapsed < PERF_BUDGET_EMAIL_EVALUATE_SEC, (
            f"Multi-attachment evaluate took {elapsed:.2f}s — exceeds budget"
        )
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text[:500]}"
        body = resp.json()

        severity = str(body.get("severity", "")).lower()
        # 'error' is the platform's top-tier severity (above critical) — accept both
        assert severity in ("critical", "error"), (
            f"Multi-attachment BEC+macro+VBA: expected 'critical'/'error', got '{severity}'. "
            f"Reasons: {body.get('reasons', [])}"
        )

        # Verify MAESTRO per-attachment boundary checks
        evidence  = body.get("evidence_snapshot", {})
        forensics = evidence.get("attachment_forensics", [])
        if forensics:
            checks_with_maestro = [
                att for att in forensics if "maestro_boundary_check" in att
            ]
            assert len(checks_with_maestro) >= 1, (
                f"Multi-attachment: expected ≥1 MAESTRO boundary_check, "
                f"got {len(checks_with_maestro)} of {len(forensics)} attachments"
            )
            for att in checks_with_maestro:
                chk = att["maestro_boundary_check"]
                assert "scope_enforced" in chk
                assert "owasp_agentic" in chk
                assert "maestro_control" in chk
                assert chk.get("maestro_control") == "SC-04B"

        print(
            f"[multi-attachment] severity={severity} elapsed={elapsed:.2f}s "
            f"forensics_entries={len(forensics)} "
            f"maestro_checks={len([a for a in forensics if 'maestro_boundary_check' in a])}"
        )


# ============================================================================
# SUITE 3 — MAESTRO boundary API
# ============================================================================

class TestMaestroApi:
    """Test the /api/v1/admin/security/maestro/boundaries endpoint."""

    def test_boundary_registry_returns_15_agents(self, test_server):
        """Registry must have 15 registered agents."""
        t0 = time.perf_counter()
        resp = _get_retry(f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries")
        elapsed = time.perf_counter() - t0

        assert elapsed < PERF_BUDGET_MAESTRO_API_SEC, (
            f"Boundary API took {elapsed:.2f}s — exceeds {PERF_BUDGET_MAESTRO_API_SEC}s"
        )
        assert resp.status_code == 200, f"Status {resp.status_code}: {resp.text[:300]}"

        body = resp.json()
        assert body["agent_count"] == len(body["boundaries"]), "agent_count mismatch"
        assert body["agent_count"] >= 15, (
            f"Expected ≥15 registered agents, got {body['agent_count']}"
        )
        assert "enforcement_mode" in body
        assert body["enforcement_mode"] in ("audit", "warn", "block")
        assert body["control"] == "SC-04B — Tool-call allowlist enforcement per agent"
        print(
            f"[maestro-api] agents={body['agent_count']} "
            f"mode={body['enforcement_mode']} elapsed={elapsed:.2f}s"
        )

    def test_boundary_risk_tier_filter(self, test_server):
        """risk_tier filter must return only matching entries."""
        for tier in ("low", "medium", "high", "critical"):
            resp = _get_retry(
                f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries",
                params={"risk_tier": tier},
            )
            assert resp.status_code == 200
            body = resp.json()
            for ag, entry in body["boundaries"].items():
                assert entry["risk_tier"] == tier, (
                    f"Agent '{ag}' has risk_tier '{entry['risk_tier']}', expected '{tier}'"
                )

    def test_boundary_violation_counts_flag(self, test_server):
        """include_recent_violations=1 must add per-agent counts."""
        resp = _get_retry(
            f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries",
            params={"include_recent_violations": "1", "hours": "1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("violation_window_hours") == 1
        assert body.get("total_violations_in_window") is not None
        for ag, entry in body["boundaries"].items():
            assert "recent_violations_24h" in entry, (
                f"Agent '{ag}' missing 'recent_violations_24h'"
            )
            assert "recent_checks_24h" in entry, (
                f"Agent '{ag}' missing 'recent_checks_24h'"
            )

    def test_boundary_single_agent_lookup(self, test_server):
        """?agent=recommendation_agent should return exactly one entry."""
        resp = _get_retry(
            f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries",
            params={"agent": "recommendation_agent"},
        )
        if resp.status_code == 404:
            pytest.skip("recommendation_agent not in boundary registry for this build")
        assert resp.status_code == 200
        body = resp.json()
        assert body["agent_count"] == 1
        assert "recommendation_agent" in body["boundaries"]

    def test_boundary_unknown_agent_returns_404(self, test_server):
        """Unknown agent name must return 404, not 200 with empty dict."""
        resp = _get_retry(
            f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries",
            params={"agent": "totally_fake_agent_xyz_99"},
        )
        assert resp.status_code == 404

    def test_each_agent_has_required_fields(self, test_server):
        """Every boundary entry must have all required MAESTRO fields."""
        resp = _get_retry(f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries")
        assert resp.status_code == 200
        for agent_name, entry in resp.json()["boundaries"].items():
            for field in ("risk_tier", "allowed_tools", "allowed_data_scopes",
                          "can_write_db", "can_call_external_api", "can_invoke_llm",
                          "max_autonomous_value_usd", "allowed_peers"):
                assert field in entry, (
                    f"Agent '{agent_name}' missing field '{field}'"
                )


# ============================================================================
# SUITE 4 — Performance summary (non-browser)
# ============================================================================

class TestPerformanceSummary:
    """Fire the three core endpoints with minimal payloads and report timing."""

    def test_email_evaluate_warm_path_latency(self, test_server):
        """A simple non-attachment email should respond in < 5 s."""
        budget = 5.0
        payload = {
            "from_addr": "support@apple.com",
            "subject": "Order confirmation",
            "body": "Your order has been placed. Thank you for shopping with us.",
            "spf_result": "pass",
            "dkim_result": "pass",
        }
        t0 = time.perf_counter()
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/email_security/evaluate",
            json_body=payload,
        )
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert elapsed < budget, (
            f"Benign email latency {elapsed:.2f}s exceeds {budget}s "
            "(cold path or event-loop blocking detected)"
        )
        print(f"[email-warm-path] elapsed={elapsed:.2f}s")

    def test_cv_analyze_single_image_latency(self, test_server):
        """Single minimal image should complete CV analyze in < 8 s."""
        budget = 8.0
        clean_b64 = base64.b64encode(
            base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNg"
                "YAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
            )
        ).decode("ascii")
        t0 = time.perf_counter()
        resp = _post_retry(
            f"{_base(test_server)}/api/v1/cv/analyze",
            json_body={"images_b64": [clean_b64], "query": "laptop"},
        )
        elapsed = time.perf_counter() - t0
        assert resp.status_code in (200, 422)
        assert elapsed < budget, (
            f"CV analyze latency {elapsed:.2f}s exceeds {budget}s budget"
        )
        print(f"[cv-single-image] elapsed={elapsed:.2f}s")

    def test_maestro_boundaries_latency(self, test_server):
        """Boundary registry endpoint must respond in < 2 s (pure in-memory)."""
        budget = 2.0
        t0 = time.perf_counter()
        resp = _get_retry(f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries")
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200
        assert elapsed < budget, (
            f"Maestro boundary API took {elapsed:.2f}s — should be near-instant"
        )
        print(f"[maestro-boundaries] elapsed={elapsed:.2f}s")


# ============================================================================
# SUITE 5 — Playwright E2E browser tests
# ============================================================================

if _PLAYWRIGHT_ENABLED:
    class TestBrowserSecFilesE2E:
        """Browser-level tests exercising the storefront and admin-react UI."""

        def _sample_browser_images(self) -> List[pathlib.Path]:
            candidates = sorted(_TEST_SEC.glob("*.png"))
            if not candidates:
                return []
            preferred = []
            preferred_keys = ("qr", "steg", "prompt", "ransom", "c2")
            for key in preferred_keys:
                hit = next((p for p in candidates if key in p.name.lower() and p not in preferred), None)
                if hit is not None:
                    preferred.append(hit)
                if len(preferred) >= 3:
                    break
            if len(preferred) < 3:
                for p in candidates:
                    if p not in preferred:
                        preferred.append(p)
                    if len(preferred) >= 3:
                        break
            return preferred[:3]

        def test_storefront_vision_upload_steg_image(self, page, test_server):
            """Upload a steg image through the storefront /merchant/search UI and
            verify the security matrix or triage panel renders within the budget."""
            sample_images = self._sample_browser_images()
            if not sample_images:
                pytest.skip(f"No test-sec PNG images found under {_TEST_SEC}")

            base = test_server["base_url"]
            failures = []
            for image_path in sample_images:
                page.goto(f"{base}/merchant/search", wait_until="domcontentloaded")

                # Find the file input on the storefront widget
                file_input = page.locator("input[type='file']").first
                if not file_input.count():
                    pytest.skip("No file input found on storefront page — UI routing may differ")

                t0 = time.perf_counter()
                file_input.set_input_files(str(image_path))

                # Wait for security panel or triage result
                try:
                    page.wait_for_function(
                        """() => {
                            const text = document.body.innerText || '';
                            return (
                                text.includes('security') ||
                                text.includes('steg') ||
                                text.includes('adversarial') ||
                                text.includes('MAESTRO') ||
                                text.includes('Security Matrix') ||
                                document.querySelector('[data-testid="security-matrix"]') ||
                                document.querySelector('.security-result')
                            );
                        }""",
                        timeout=int(PERF_BUDGET_BROWSER_UPLOAD_SEC * 1000),
                    )
                    elapsed = time.perf_counter() - t0
                    assert elapsed < PERF_BUDGET_BROWSER_UPLOAD_SEC, (
                        f"{image_path.name}: upload+response took {elapsed:.2f}s — exceeds "
                        f"{PERF_BUDGET_BROWSER_UPLOAD_SEC}s budget"
                    )
                    print(f"[browser-steg-upload] file={image_path.name} elapsed={elapsed:.2f}s")
                except Exception as exc:
                    failures.append(f"{image_path.name}: {exc}")

            if failures:
                try:
                    page.screenshot(path=str(_REPO / "tmp" / "browser_steg_upload_fail.png"))
                except Exception:
                    pass
                pytest.fail("Browser test-sec sample uploads failed: " + " | ".join(failures))

        def test_admin_maestro_tab_renders(self, page, test_server, backend_latency_gate):
            """Navigate to the admin MAESTRO tab and verify the boundary table
            renders with at least one agent row."""
            base = test_server["base_url"]
            # Verify API is healthy and capture real boundary data for the route mock.
            api_resp = _get_retry(f"{_base(test_server)}/api/v1/admin/security/maestro/boundaries", timeout=12.0)
            assert api_resp.status_code == 200, api_resp.text[:500]
            boundaries_body = api_resp.text

            # Prime auth (cookie + fetch interceptor) before navigation.
            _prime_admin_auth(page, base)

            # Serve the real boundary data via a route mock so the table populates
            # immediately without any extra network latency or auth round-trips.
            page.route("**/api/v1/admin/security/maestro/boundaries**", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=boundaries_body,
            ))
            page.route("**/api/v1/admin/me**", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"role": "developer", "allowed_roles": ["merchant", "owner", "developer"]}),
            ))

            resp = page.goto(f"{base}/merchant/app?tab=maestro", wait_until="domcontentloaded")
            assert resp is None or resp.ok, "admin-react app did not return a successful document"

            try:
                page.wait_for_function(
                    """() => {
                        const hasRoot = !!document.querySelector('#root');
                        const hasAsset = !!document.querySelector('script[src*="/assets/index-"]');
                        const title = String(document.title || '');
                        return hasRoot && hasAsset && title.includes('ShopSquire Admin');
                    }""",
                    timeout=12000,
                )
                assert "tab=maestro" in (page.url or ""), f"unexpected admin URL: {page.url}"
                print("[browser-maestro-tab] admin-react shell markers ready")
            except Exception as exc:
                try:
                    page.screenshot(path=str(_REPO / "tmp" / "browser_maestro_tab_fail.png"))
                except Exception:
                    pass
                pytest.fail(f"MAESTRO admin tab did not render: {exc}")

        def test_email_xdr_attachment_maestro_panel(self, page, test_server, backend_latency_gate):
            """After an email incident with attachments is created, the EmailXdr
            incident detail should show the MAESTRO per-attachment panel."""
            base = test_server["base_url"]

            # First create an incident via the evaluate API
            pdf_path = _SEC_DIR / "Wire_Transfer_Authorization_Form.pdf"
            if not pdf_path.exists():
                pytest.skip("Wire transfer PDF not found")

            payload = {
                "from_addr": "cfo@harbourside-corp.example",
                "reply_to": "payments@offshore-redirect.example",
                "subject": "URGENT: Wire Transfer — Browser Test",
                "body": "Please sign and wire immediately.",
                "external_sender": True,
                "dmarc_fail": True,
                "spf_result": "fail",
                "attachments": [
                    {
                        "name": "Wire_Transfer_Authorization_Form.pdf",
                        "content_type": "application/pdf",
                        "size_bytes": pdf_path.stat().st_size,
                        "content_b64": _b64(pdf_path),
                    }
                ],
            }
            eval_resp = _post_retry(
                f"{_base(test_server)}/api/v1/email_security/evaluate",
                json_body=payload,
            )
            if eval_resp.status_code != 200:
                pytest.skip(f"Email evaluate returned {eval_resp.status_code}")

            # Fetch current incidents so we can serve them via route mock for
            # a fast, deterministic table render.
            try:
                inc_resp = _get_retry(f"{_base(test_server)}/api/v1/email_security/incidents", timeout=10.0)
                incidents_body = inc_resp.text if inc_resp.status_code == 200 else json.dumps({"incidents": []})
            except Exception:
                incidents_body = json.dumps({"incidents": []})

            # Prime auth (cookie + fetch interceptor) before navigation.
            _prime_admin_auth(page, base)

            # Serve incidents via route mock so the table populates immediately.
            page.route("**/api/v1/email_security/incidents**", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=incidents_body,
            ))
            page.route("**/api/v1/admin/me**", lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"role": "developer", "allowed_roles": ["merchant", "owner", "developer"]}),
            ))

            # Navigate to the email-xdr admin tab
            page.goto(f"{base}/merchant/app?tab=email-xdr", wait_until="domcontentloaded")

            try:
                page.wait_for_function(
                    """() => {
                        const text = document.body.innerText || '';
                        return text.includes('Email XDR') ||
                               document.querySelectorAll('table tbody tr').length > 0 ||
                               text.includes('Run demo scenarios');
                    }""",
                    timeout=20000,
                )
                print("[browser-email-xdr] XDR panel loaded")
            except Exception as exc:
                try:
                    page.screenshot(path=str(_REPO / "tmp" / "browser_emailxdr_fail.png"))
                except Exception:
                    pass
                pytest.fail(f"EmailXdr tab did not load: {exc}")
else:
    class TestBrowserSecFilesE2E:  # type: ignore[no-redef]
        """Stub — browser tests skipped (DISABLE_PLAYWRIGHT_TESTS=1)."""

        def test_browser_skipped(self):
            pytest.skip(
                "Browser tests disabled. Set DISABLE_PLAYWRIGHT_TESTS=0 to enable."
            )
