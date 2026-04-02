from pathlib import Path
import os

import pytest

from src.app.security.email_eval_matrix import build_evaluation_report


@pytest.mark.skipif(
    not os.getenv("PYTEST_FULL_INTEGRATION"),
    reason="Heavy integration test (steg + QR on real attachments). Set PYTEST_FULL_INTEGRATION=1 to enable.",
)
@pytest.mark.timeout(300)
def test_email_eval_matrix_builds_expected_cases_when_fixtures_present():
    root = Path(__file__).resolve().parents[2]
    if not ((root / "dump" / "email-2" / "files").exists() or (root / "dump" / "email").exists()):
        return

    report = build_evaluation_report()
    assert isinstance(report, dict)
    cases = report.get("cases") or []
    by_id = {str(c.get("case_id") or ""): c for c in cases if isinstance(c, dict)}

    assert "email2_full_pack" in by_id
    email2 = by_id["email2_full_pack"]
    assert email2.get("severity") == "error"
    assert any(
        v.get("vector") == "payment_diversion" and v.get("status") == "pass"
        for v in (email2.get("threat_vector_matrix") or [])
        if isinstance(v, dict)
    )
    assert any(
        a.get("agent") == "attachment_forensics_agent" and a.get("status") == "pass"
        for a in (email2.get("agent_matrix") or [])
        if isinstance(a, dict)
    )

    if "ingram_pdf_pair" in by_id:
        ingram = by_id["ingram_pdf_pair"]
        assert any(
            a.get("agent") == "baseline_agent" and a.get("status") == "pass"
            for a in (ingram.get("agent_matrix") or [])
            if isinstance(a, dict)
        )

    redteam = report.get("redteam_matrix") or {}
    assert isinstance(redteam, dict)
    assert redteam.get("matrix_version") in {"email_redteam_matrix.v1", None}
    redteam_cases = redteam.get("cases") or []
    if redteam_cases:
        by_case = {str(c.get("case_id") or ""): c for c in redteam_cases if isinstance(c, dict)}
        assert "supplier_invoice_mixed_pack" in by_case
        first = by_case["supplier_invoice_mixed_pack"]
        assertions = first.get("matrix_assertions") or {}
        assert assertions.get("status") in {"pass", "fail"}
        checks = assertions.get("checks") or []
        assert isinstance(checks, list) and checks
        assert any(case_id in by_case for case_id in {"safe_supplier_demo_pack", "qr_privacy_lane", "hidden_payload_hunter_lane", "macro_fileless_context_lane"})
