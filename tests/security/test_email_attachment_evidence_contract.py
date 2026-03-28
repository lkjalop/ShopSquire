import base64
from pathlib import Path

from src.app.security.email_security import evaluate_email_security


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def test_attachment_evidence_contract_for_xlsm_pdf_bas_triplet():
    base = Path("dump/Sec")
    payload = {
        "message_id": "msg-evidence-contract",
        "from_addr": "finance@balashnikovai.com.au",
        "reply_to": "finance@balashnikovai.com.au",
        "subject": "Updated Payment Details",
        "body": "Please process the updated payment details in the attached documents.",
        "attachments": [
            {
                "name": "Harbourside_Acquisition_Details_CONFIDENTIAL (1).xlsm",
                "content_type": "application/vnd.ms-excel.sheet.macroEnabled.12",
                "content_b64": _b64(base / "Harbourside_Acquisition_Details_CONFIDENTIAL (1).xlsm"),
            },
            {
                "name": "VBA_SOURCE_SecurityModule.bas",
                "content_type": "text/plain",
                "content_b64": _b64(base / "VBA_SOURCE_SecurityModule.bas"),
            },
            {
                "name": "Wire_Transfer_Authorization_Form.pdf",
                "content_type": "application/pdf",
                "content_b64": _b64(base / "Wire_Transfer_Authorization_Form.pdf"),
            },
        ],
        "dmarc_fail": False,
    }
    out = evaluate_email_security(payload, tenant_id="tenant-evidence-contract")
    sa = (((out or {}).get("evidence_snapshot") or {}).get("security_analysis") or {})
    findings = list((((out or {}).get("evidence_snapshot") or {}).get("structured_findings") or []))
    framework_rows = list(sa.get("framework_rows") or [])
    possible_framework_rows = list(sa.get("possible_framework_rows") or [])

    assert sa.get("mitre_atlas") == []
    assert "AML.T0043" not in (sa.get("possible_mitre_atlas") or [])
    assert sa.get("validated_pasta_stage") != "Stage6:ModellingAndSimulation"

    observed_attack = set(sa.get("mitre_attack") or [])
    possible_attack = set(sa.get("possible_mitre_attack") or [])
    assert observed_attack == set()
    assert "T1566.001" in possible_attack or "T1566.002" in possible_attack
    assert "T1071.001" not in observed_attack
    assert "T1071.001" in possible_attack or "T1105" in possible_attack
    assert sa.get("evidence_quality", {}).get("numeric_withheld") is True

    for row in framework_rows + possible_framework_rows:
      assert row.get("evidence_refs"), f"framework row missing refs: {row}"

    suppressed = [f for f in findings if str(f.get("claim_status") or "") == "suppressed"]
    observed = [f for f in findings if str(f.get("claim_status") or "") in {"observed", "inferred"}]
    possible = [f for f in findings if str(f.get("claim_status") or "") == "possible"]

    assert any(str(f.get("finding_type") or "") == "macro_auto_execution_lure" for f in observed)
    assert any(str(f.get("finding_type") or "") == "lolbin_command_sequence" for f in possible)
    assert any(str(f.get("finding_type") or "") == "c2_beacon_pattern" for f in possible)
    assert any(str(f.get("finding_group") or "") == "detection_artifact_patterns" for f in suppressed)

    for finding in observed + possible:
        assert finding.get("artifact_provenance"), f"finding missing provenance: {finding}"
        assert finding.get("evidence_refs"), f"finding missing refs: {finding}"

    top_summary_ids = {str(row.get("control_or_tag") or "") for row in framework_rows if str(row.get("framework") or "") == "MITRE ATT&CK"}
    assert "T1071.001" not in top_summary_ids
    possible_summary_ids = {str(row.get("control_or_tag") or "") for row in possible_framework_rows if str(row.get("framework") or "") == "MITRE ATT&CK"}
    assert "T1071.001" in possible_summary_ids or "T1105" in possible_summary_ids
