from __future__ import annotations

import base64
import os


def _set_env(monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./test_email_ransomware_artifact_pack.db")
    monkeypatch.setenv("DATABASE_URL_RO", "sqlite:///./test_email_ransomware_artifact_pack.db")
    monkeypatch.setenv("DECISION_LOG_WRITES_ENABLED", "1")


def test_ransomware_artifact_detector_signals_all_four():
    from src.app.security.ransomware_detector import analyze_ransomware_artifacts

    payload = {
        "subject": "Invoice macro test",
        "body": (
            "WINWORD.EXE -> cmd.exe -> powershell.exe ; vssadmin delete shadows /all /quiet. "
            "Canary.docx will be encrypted first."
        ),
        "attachments": [
            {
                "name": "invoice.docm",
                "content_b64": base64.b64encode(os.urandom(4096)).decode("ascii"),
                "extracted_text": "AutoOpen() Shell(\"powershell -enc AAA\")",
            }
        ],
    }
    out = analyze_ransomware_artifacts(payload)
    assert str(out.get("mode")) == "artifact_only_pre_execution"
    assert int(out.get("signal_count") or 0) >= 4
    types = {str(i.get("type") or "") for i in (out.get("indicators") or [])}
    assert "ransomware_attachment_entropy_hint" in types
    assert "ransomware_shadow_copy_deletion_command" in types
    assert "ransomware_canary_targeting_pattern" in types
    assert "ransomware_office_to_script_chain_indicator" in types


def test_email_security_includes_ransomware_artifact_pack_and_coverage(monkeypatch):
    _set_env(monkeypatch)
    from src.app.security.email_security import evaluate_email_security

    out = evaluate_email_security(
        {
            "message_id": "<p2-ransomware-artifact@x>",
            "from_addr": "Ops <ops@supplier.com>",
            "reply_to": "ops@supplier.com",
            "subject": "Document update",
            "body": (
                "WINWORD.EXE launching cmd.exe then powershell.exe. "
                "Also execute vssadmin delete shadows /all /quiet."
            ),
            "attachments": [{"name": "invoice.docm", "extracted_text": "Document_Open -> Shell(\"powershell\")"}],
            "external_sender": True,
            "dmarc_fail": False,
        },
        tenant_id="tenant-ransomware-p2",
    )
    types = {str(i.get("type") or "") for i in (out.get("indicators") or [])}
    assert "ransomware_shadow_copy_deletion_command" in types
    assert "ransomware_office_to_script_chain_indicator" in types
    assert str(out.get("route") or "") == "security_review"
    coverage = out.get("coverage_limits") or {}
    assert str(coverage.get("positioning") or "") == "ShopSquire is the pre-execution gate; EDR is the post-execution backstop."
    ev = out.get("evidence_snapshot") or {}
    assert isinstance(ev.get("ransomware_artifact"), dict)
    assert isinstance(ev.get("coverage_limits"), dict)
