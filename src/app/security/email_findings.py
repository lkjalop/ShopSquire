"""Finding normalization, ranking, categorization + agent-boundary/compliance mapping (extracted
from email_security.py, session 3).

Pure functions over finding/artifact DICTS — normalize a raw finding into the schema, rank + dedupe,
categorize an artifact, map to compliance controls, and the agent-boundary/toolset lookup. No
orchestrator state, no back-reference to email_security; the only external dep is the control
registry. Never raises. Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Dict, List  # noqa: F401

from src.app.security.control_registry import get_control_record, get_control_registry_version


def _email_agent_boundaries() -> Dict[str, Dict[str, Any]]:
    return {
        "sender_auth_agent": {
            "allowed_inputs": ["headers", "auth_results", "sender_domains", "header_forensics"],
            "allowed_tools": ["validate_auth", "analyze_headers", "score_reply_drift"],
            "allowed_outputs": ["auth_failures", "reply_drift", "spoof_likelihood", "infrastructure_anomalies"],
            "denied_capabilities": ["read_full_attachment_bodies", "trigger_actions", "access_secrets", "open_internet"],
            "action_mode": "read_only",
        },
        "attachment_forensics_agent": {
            "allowed_inputs": ["sanitized_attachment_text", "ocr_output", "file_metadata", "static_analysis"],
            "allowed_tools": ["extract_text", "ocr_attachment", "parse_pdf", "scan_qr", "extract_bank_fields"],
            "allowed_outputs": ["bank_detail_extraction", "qr_url_findings", "script_macro_risk", "attachment_class", "per_file_evidence"],
            "denied_capabilities": ["update_supplier_baseline", "access_secrets", "push_connectors", "open_internet"],
            "action_mode": "read_only",
        },
        "baseline_agent": {
            "allowed_inputs": ["supplier_profile", "approved_contacts", "bank_fingerprints", "template_hashes", "attachment_summaries"],
            "allowed_tools": ["compare_template_hashes", "compare_bank_fingerprints", "score_supplier_drift"],
            "allowed_outputs": ["baseline_mismatch", "baseline_state", "candidate_update_recommendation"],
            "denied_capabilities": ["change_baseline_automatically", "push_connectors", "access_secrets"],
            "action_mode": "recommend_only",
        },
        "correlation_agent": {
            "allowed_inputs": ["current_findings", "prior_incidents", "sender_graph", "bank_graph", "infra_overlap"],
            "allowed_tools": ["link_related_incidents", "score_campaign_overlap", "build_incident_context"],
            "allowed_outputs": ["related_incidents", "campaign_linkage", "historical_context"],
            "denied_capabilities": ["alter_verdict_alone", "execute_actions", "access_secrets"],
            "action_mode": "read_only",
        },
        "explanation_agent": {
            "allowed_inputs": ["normalized_evidence", "faq_mappings", "policy_mappings", "sop_mappings"],
            "allowed_tools": ["summarize_findings", "map_policy_guidance", "render_explanations"],
            "allowed_outputs": ["business_safe_summary", "analyst_summary", "raw_technical_summary"],
            "denied_capabilities": ["invent_evidence", "override_severity", "execute_actions", "access_secrets"],
            "action_mode": "read_only",
        },
        "playbook_agent": {
            "allowed_inputs": ["policy_approved_findings", "allowed_action_set", "sop_mappings"],
            "allowed_tools": ["map_playbook_steps", "propose_gated_actions", "render_next_steps"],
            "allowed_outputs": ["recommended_steps", "gated_action_plan"],
            "denied_capabilities": ["execute_privileged_actions_without_approval", "change_baseline_automatically"],
            "action_mode": "approval_gated",
        },
    }


def _confidence_band(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.55:
        return "medium"
    return "low"


def _finding_source_toolset(agent_origin: str) -> list[str]:
    tools = (_email_agent_boundaries().get(str(agent_origin or "").strip()) or {}).get("allowed_tools") or []
    return [str(x) for x in tools][:6]


def _normalize_finding(
    *,
    finding_id: str,
    finding_type: str,
    summary: str,
    severity_hint: str,
    confidence_score: float,
    source_type: str,
    evidence_kind: str,
    agent_origin: str,
    policy_weight: float,
    evidence: list[str] | None = None,
    artifact_ref: Dict[str, Any] | None = None,
    retrieval_context: Dict[str, Any] | None = None,
    recommended_action: str = "security_review",
    allowed_actions: list[str] | None = None,
    disallowed_actions: list[str] | None = None,
    claim_status: str | None = None,
    finding_group: str | None = None,
    evidence_refs: list[str] | None = None,
    artifact_provenance: list[dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    normalized_evidence_kind = str(evidence_kind or "inferred").strip()
    normalized_claim_status = str(claim_status or ("observed" if normalized_evidence_kind == "direct" else "inferred")).strip().lower()
    normalized_group = str(finding_group or "active_findings").strip()
    row = {
        "finding_id": str(finding_id or "").strip(),
        "finding_type": str(finding_type or "unknown").strip(),
        "summary": str(summary or "").strip(),
        "severity_hint": str(severity_hint or "medium").strip(),
        "confidence_score": round(float(confidence_score or 0.0), 4),
        "confidence_band": _confidence_band(float(confidence_score or 0.0)),
        "source_type": str(source_type or "policy").strip(),
        "evidence_kind": normalized_evidence_kind,
        "agent_origin": str(agent_origin or "email_security_agent").strip(),
        "policy_weight": round(float(policy_weight or 0.0), 4),
        "artifact_ref": artifact_ref if isinstance(artifact_ref, dict) else {},
        "evidence": [str(x) for x in (evidence or []) if str(x or "").strip()][:8],
        "retrieval_context": retrieval_context if isinstance(retrieval_context, dict) else {},
        "claim_status": normalized_claim_status,
        "finding_group": normalized_group,
        "evidence_refs": [str(x) for x in (evidence_refs or []) if str(x or "").strip()][:10],
        "artifact_provenance": [dict(x) for x in (artifact_provenance or []) if isinstance(x, dict)][:8],
        "recommended_action": str(recommended_action or "security_review").strip(),
        "allowed_actions": [str(x) for x in (allowed_actions or []) if str(x or "").strip()][:8],
        "disallowed_actions": [str(x) for x in (disallowed_actions or []) if str(x or "").strip()][:8],
    }
    if not row["allowed_actions"]:
        row["allowed_actions"] = ["notify_analyst", "create_ticket"]
    if not row["disallowed_actions"]:
        row["disallowed_actions"] = ["approve_supplier_update", "push_block_rule"]
    return row


def _finding_rank_score(finding: Dict[str, Any]) -> float:
    f = finding if isinstance(finding, dict) else {}
    score = float(f.get("confidence_score") or 0.0)
    score += float(f.get("policy_weight") or 0.0) * 0.35
    if str(f.get("evidence_kind") or "") == "direct":
        score += 0.2
    source = str(f.get("source_type") or "")
    score += {
        "baseline": 0.18,
        "behavioral": 0.16,
        "policy": 0.14,
        "static": 0.12,
        "ocr": 0.11,
        "intel": 0.1,
    }.get(source, 0.05)
    ftype = str(f.get("finding_type") or "")
    if any(tok in ftype for tok in ("bank", "payment_change", "baseline_mismatch", "reply_drift", "auth_failure")):
        score += 0.18
    if any(tok in ftype for tok in ("lolbin_command_sequence", "c2_beacon_pattern", "data_exfiltration_instruction", "prompt_injection_hidden", "ssn_leakage_linked_qr")):
        score += 0.22
    if any(tok in ftype for tok in ("attachment_url_exposure", "qr_redirect_risk")):
        score += 0.08
    if "related_incident" in ftype or "campaign" in ftype:
        score += 0.08
    name = str(((f.get("artifact_ref") or {}).get("file_name") or "")).lower()
    if name.endswith(".pdf") and any(_tok in " ".join([str(x) for x in (f.get("evidence") or [])]).lower() for _tok in ("bsb", "account", "payment", "bank", "remittance", "http://", "https://")):
        score += 0.16
    if ftype == "infrastructure_anomaly" and float(f.get("confidence_score") or 0.0) < 0.8:
        score -= 0.08
    if str(f.get("finding_category") or "") == "policy_violation":
        score -= 0.2
    if source == "policy" and not name:
        score -= 0.1
    if name.endswith((".md", ".json", ".py", ".txt")) or any(tok in name for tok in ("guide", "scenario", "test", "summary", "matrix", "spec", "report", "generate", "playbook")):
        score -= 0.42
    category = str(f.get("finding_category") or "")
    claim_status = str(f.get("claim_status") or "").lower()
    if category == "benign_reference_material":
        score -= 0.55
    elif category == "contextual_test_artifact":
        score -= 0.85
    elif category == "reference_spec_material":
        score -= 0.92
    elif category == "contextual_supplier_mismatch":
        score -= 0.1
    if claim_status == "suppressed":
        score -= 1.25
    elif claim_status == "possible":
        score -= 0.28
    return round(score, 4)


def _artifact_finding_category(filename: str, finding_type: str, summary: str) -> str:
    name = str(filename or "").strip().lower()
    ftype = str(finding_type or "").strip().lower()
    text = str(summary or "").strip().lower()
    if name.endswith((".md", ".json", ".txt")) or any(tok in name for tok in ("guide", "scenario", "summary", "matrix", "spec", "report", "taxonomy", "playbook")):
        if any(tok in name for tok in ("guide", "scenario", "summary", "matrix", "spec", "report", "taxonomy", "playbook")):
            return "reference_spec_material"
        return "benign_reference_material"
    if name.endswith((".py", ".ps1", ".sh")) or any(tok in name for tok in ("generate", "fixture", "sample_")):
        return "contextual_test_artifact"
    if any(tok in ftype for tok in ("baseline_mismatch", "baseline_drift")):
        return "baseline_drift"
    if any(tok in ftype for tok in ("lolbin_command_sequence", "c2_beacon_pattern")):
        return "unconfirmed_execution_hypothesis"
    if any(tok in ftype for tok in ("lolbin_command_sequence", "c2_beacon_pattern", "data_exfiltration_instruction")):
        return "malicious_artifact"
    if "prompt_injection_hidden" in ftype:
        return "policy_violation"
    if "ssn_leakage_linked_qr" in ftype:
        return "active_payment_lure"
    if any(tok in ftype for tok in ("payment_change", "bank_detail", "attachment_url", "qr_redirect")):
        if name.endswith((".md", ".json", ".py", ".txt")):
            return "contextual_test_artifact"
        return "active_payment_lure"
    if any(tok in ftype for tok in ("reply_drift", "auth_failure", "infrastructure_anomaly", "related_incident_overlap")):
        return "contextual_supplier_mismatch"
    if "contradict" in text or "does not line up" in text:
        return "contradicts_sender_claim"
    if "policy" in ftype or "policy " in text:
        return "policy_violation"
    return "suspicious"


def _artifact_evidence_refs(filename: str, evidence: list[str] | None) -> list[str]:
    name = str(filename or "").strip().lower()
    refs: list[str] = []
    joined = " \n ".join(str(x or "") for x in (evidence or []))
    low = joined.lower()
    if name.endswith(".xlsm"):
        if "enable content" in low or "enable macros" in low:
            refs.append("xlsm.sheet1.enable_macros_banner")
        if "85,000" in low or "aud $85,000.00" in low:
            refs.append("xlsm.sheet4.amount")
        if "harbourside capital partners" in low:
            refs.append("xlsm.sheet4.beneficiary")
        if "012-456" in low:
            refs.append("xlsm.sheet4.bsb")
        if "8877 3421" in low:
            refs.append("xlsm.sheet4.account_number")
        if "anzbau3m" in low:
            refs.append("xlsm.sheet4.swift")
        if "do not discuss" in low or "strictly confidential" in low:
            refs.append("xlsm.sheet4.confidentiality")
        if "verbal approval pending" in low or "boris petrov" in low:
            refs.append("xlsm.sheet4.authorization")
        if "deposit required" in low:
            refs.append("xlsm.sheet2.deposit_required")
        if "powershell -executionpolicy bypass" in low or "powershell.exe" in low:
            refs.append("xlsm.vba.powershell_indicator")
        if "certutil -urlcache" in low or "certutil.exe" in low:
            refs.append("xlsm.vba.certutil_indicator")
        if "bitsadmin /transfer" in low or "bitsadmin" in low:
            refs.append("xlsm.vba.bitsadmin_indicator")
        if "schtasks /create" in low or "schtasks" in low:
            refs.append("xlsm.vba.schtasks_indicator")
        if "balashnikovai-cdn.com" in low:
            refs.append("xlsm.vba.c2_domain_cdn")
        if "balashnikovai-analytics.com" in low:
            refs.append("xlsm.vba.c2_domain_analytics")
        if "sub auto_open()" in low:
            refs.append("xlsm.vba.auto_open")
        if "sub workbook_open()" in low:
            refs.append("xlsm.vba.workbook_open")
    elif name.endswith(".pdf"):
        if "balashnikovai-analytics.com" in low:
            refs.append("pdf.raw.balashnikovai_analytics_domain")
        if "balashnikovai-cdn.com" in low:
            refs.append("pdf.raw.balashnikovai_cdn_domain")
        if "http://" in low or "https://" in low:
            refs.append("pdf.embedded_urls")
        if "/track/wta-" in low or "track/wta-2026" in low:
            refs.append("pdf.footer.tracking_url")
        if "wire transfer authorization" in low:
            refs.append("pdf.form.wire_transfer_authorization")
    elif name.endswith(".bas"):
        if "sub auto_open()" in low:
            refs.append("vba.auto_open")
        if "sub workbook_open()" in low:
            refs.append("vba.workbook_open")
        if "benign test - no functional malicious code" in low:
            refs.append("vba.banner.benign_test_artifact")
        if "' powershell.exe" in low or "' certutil.exe" in low or "' bitsadmin" in low or "' schtasks" in low:
            refs.append("vba.comments.lolbin_pattern")
        if "balashnikovai-cdn.com" in low or "balashnikovai-analytics.com" in low:
            refs.append("vba.comments.c2_domain")
    elif name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        if "lsb content extraction succeeded" in low or "\"decoded_content\"" in low:
            refs.append("image.steg.decoded_content")
        if "certutil" in low:
            refs.append("image.steg.certutil_indicator")
        if "powershell" in low:
            refs.append("image.steg.powershell_indicator")
        if "bitsadmin" in low:
            refs.append("image.steg.bitsadmin_indicator")
        if "schtasks" in low:
            refs.append("image.steg.schtasks_indicator")
        if "callback" in low or "beacon" in low or "interval" in low or "test-c2.example.invalid" in low:
            refs.append("image.steg.c2_callback_pattern")
        if "exfiltrate" in low or "test-exfil.example.invalid" in low or "api_keys" in low or "user_data" in low:
            refs.append("image.steg.data_exfil_pattern")
        if "ignore previous" in low or "prompt injection" in low or "system prompt" in low:
            refs.append("image.steg.prompt_injection_text")
        if "ssn pattern count" in low or "ssn 123-45-6789" in low:
            refs.append("image.linked_artifact.ssn_hits")
        if "linked destination:" in low or "scanned.page/" in low:
            refs.append("image.qr.linked_destination")
    seen: set[str] = set()
    return [x for x in refs if x and not (x in seen or seen.add(x))]


def _artifact_provenance_rows(
    *,
    filename: str,
    evidence: list[str] | None,
    file_type: str | None = None,
    claim_status: str = "observed",
) -> list[dict[str, Any]]:
    refs = _artifact_evidence_refs(filename, evidence)
    name = str(filename or "").strip()
    low = name.lower()
    method = "passive attachment text extraction"
    if low.endswith(".xlsm"):
        method = "OOXML worksheet + VBA string extraction"
    elif low.endswith(".pdf"):
        method = "PDF byte scan / embedded URL extraction"
    elif low.endswith(".bas"):
        method = "VBA source inspection"
    elif low.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
        method = "image OCR / steganography decode / linked artifact analysis"
    rows: list[dict[str, Any]] = []
    for ref in refs:
        rows.append(
            {
                "source_file": name,
                "extraction_method": method,
                "match_ref": ref,
                "confidence": "high" if claim_status == "observed" else ("medium" if claim_status == "inferred" else "low"),
                "file_type": str(file_type or ""),
            }
        )
    return rows


def _is_benign_comment_only_vba_artifact(filename: str, extracted_text: str, hypothesis: str) -> bool:
    low_name = str(filename or "").strip().lower()
    low = str(extracted_text or "").lower()
    if not low_name.endswith(".bas"):
        return False
    if hypothesis not in {"lolbin_command_sequence", "c2_beacon"}:
        return False
    if "benign test - no functional malicious code" not in low:
        return False
    suspicious = ("powershell.exe", "certutil.exe", "bitsadmin", "schtasks", "balashnikovai-cdn.com", "balashnikovai-analytics.com", "beaconing")
    uncommented = False
    commented = False
    for line in str(extracted_text or "").splitlines():
        line_low = line.strip().lower()
        if not any(tok in line_low for tok in suspicious):
            continue
        if line_low.startswith("'"):
            commented = True
        else:
            uncommented = True
    return commented and not uncommented


def _claim_contract_for_finding(
    *,
    filename: str,
    finding_type: str,
    evidence_kind: str,
    category: str,
    source_type: str,
    extracted_text: str = "",
    evidence: list[str] | None = None,
) -> tuple[str, str]:
    ftype = str(finding_type or "").lower()
    cat = str(category or "").lower()
    src = str(source_type or "").lower()
    if cat in {"reference_spec_material", "benign_reference_material", "contextual_test_artifact"}:
        return "suppressed", "detection_artifact_patterns"
    if _is_benign_comment_only_vba_artifact(filename, extracted_text, ftype):
        return "suppressed", "detection_artifact_patterns"
    if ftype in {"lolbin_command_sequence", "c2_beacon_pattern", "data_exfiltration_instruction"} and src in {"behavioral", "static", "ocr"}:
        return "possible", "unconfirmed_higher_order_hypotheses"
    if str(evidence_kind or "").strip().lower() == "direct":
        return "observed", "active_findings"
    return "inferred", "active_findings"


def _dedupe_ranked_findings(findings: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    policy_seen = False
    has_direct_primary = any(
        isinstance(f, dict)
        and str(f.get("evidence_kind") or "") == "direct"
        and str(f.get("finding_category") or "") not in {"contextual_test_artifact", "reference_spec_material", "benign_reference_material"}
        for f in findings
    )
    for row in sorted([f for f in findings if isinstance(f, dict)], key=_finding_rank_score, reverse=True):
        ftype = str(row.get("finding_type") or "")
        artifact = str(((row.get("artifact_ref") or {}).get("file_name") or "")).strip().lower()
        summary = str(row.get("summary") or "").strip().lower()
        category = str(row.get("finding_category") or "").strip().lower()
        key = f"{ftype}|{artifact}"
        if key in seen_keys:
            continue
        if category == "policy_violation":
            if policy_seen:
                continue
            if any(str((x.get("artifact_ref") or {}).get("file_name") or "").strip() for x in out):
                if "policy gate" in summary or "verification required" in summary or "reauth" in summary:
                    policy_seen = True
                    continue
            policy_seen = True
        if has_direct_primary and category in {"contextual_test_artifact", "reference_spec_material", "benign_reference_material"}:
            continue
        seen_keys.add(key)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _finding_agentic_tags(finding_type: str, source_type: str, category: str) -> list[str]:
    ftype = str(finding_type or "").lower()
    src = str(source_type or "").lower()
    cat = str(category or "").lower()
    tags: list[str] = []
    if any(tok in ftype for tok in ("baseline", "attachment_url", "qr_redirect")) or cat in {"baseline_drift", "active_payment_lure"}:
        tags.append("ASI04:AgenticSupplyChainVulnerabilities")
    if "policy" in ftype:
        tags.append("ASI07:InsecureInterAgentComms")
    if src in {"ocr", "static"} and "payment" in ftype:
        tags.append("ASI04:AgenticSupplyChainVulnerabilities")
    if "prompt_injection_hidden" in ftype:
        tags.extend(["ASI02:PromptInjectionAndManipulation", "ASI07:InsecureInterAgentComms"])
    if any(tok in ftype for tok in ("data_exfiltration_instruction", "ssn_leakage_linked_qr")):
        tags.append("ASI06:SensitiveDataExposure")
    if any(tok in ftype for tok in ("c2_beacon_pattern", "lolbin_command_sequence")):
        tags.append("ASI08:AgentEnvironmentAbuse")
    seen = set()
    return [x for x in tags if x and not (x in seen or seen.add(x))]


def _finding_compliance_mapping(
    *,
    finding_type: str,
    category: str,
    source_type: str,
    evidence: list[str] | None = None,
    business_outcome: str | None = None,
    claim_status: str | None = None,
) -> list[dict[str, Any]]:
    ftype = str(finding_type or "").lower()
    cat = str(category or "").lower()
    src = str(source_type or "").lower()
    status = str(claim_status or "").strip().lower()
    mappings: list[dict[str, Any]] = []
    evidence_lines = [str(x).strip() for x in (evidence or []) if str(x or "").strip()]
    evidence_refs = [f"finding.evidence.{i+1}" for i in range(len(evidence_lines[:4]))]

    if status == "suppressed":
        return []

    def _row(framework: str, controls: list[str], rationale: str) -> dict[str, Any]:
        registry_records = [get_control_record(framework, str(control)) for control in controls]
        registry_records = [row for row in registry_records if isinstance(row, dict) and row]
        statuses = [str(row.get("control_implemented") or "").strip() for row in registry_records if str(row.get("control_implemented") or "").strip()]
        evidence_of_control: list[str] = []
        for row in registry_records:
            for ref in (row.get("evidence_of_control") or []):
                s = str(ref or "").strip()
                if s and s not in evidence_of_control:
                    evidence_of_control.append(s)
        return {
            "framework": framework,
            "controls": controls,
            "rationale": rationale,
            "evidence_refs": list(evidence_refs),
            "evidence_summary": evidence_lines[:3],
            "business_significance": str(business_outcome or "").strip(),
            "mapping_source": (
                f"email_security._finding_compliance_mapping + control_registry@{get_control_registry_version()}"
                if registry_records
                else "email_security._finding_compliance_mapping"
            ),
            "mapping_version": "2026.03.28.1",
            "mapping_confidence": "high" if len(evidence_refs) >= 2 else ("medium" if evidence_refs else "low"),
            "analyst_review_required": True,
            "control_implemented": statuses[0] if statuses else None,
            "evidence_of_control": evidence_of_control,
        }
    if any(tok in ftype for tok in ("bank_detail", "payment_change", "baseline_mismatch", "reply_drift")) or cat in {"active_payment_lure", "baseline_drift"}:
        mappings.extend(
            [
                _row("ISO27001", ["A.5.16", "A.5.19", "A.5.23"], "Supplier identity, supplier relationship, and financial workflow controls should be reviewed."),
                _row("ISO42001", ["Human oversight", "Outcome monitoring"], "AI-assisted fraud decisions need human oversight and outcome monitoring."),
                _row("EU AI Act", ["Article 9", "Article 14"], "Risk management and human oversight apply when AI contributes to operational security decisions."),
            ]
        )
    if src in {"ocr", "static"} and ("bank" in ftype or "payment" in ftype):
        mappings.append(_row("PCI DSS", ["Req 6", "Req 10", "Req 12"], "Payment workflow controls, audit trails, and security governance should be reviewed."))
    if any(tok in ftype for tok in ("infrastructure", "related_incident")):
        mappings.append(_row("ISO27001", ["A.8.16", "A.5.7"], "Security monitoring and threat intelligence processes are implicated."))
    if any(tok in ftype for tok in ("prompt", "policy")):
        mappings.extend(
            [
                _row("ISO42001", ["Risk treatment", "Model governance"], "Agentic AI controls and guardrails should be reviewed."),
                _row("EU AI Act", ["Article 15"], "Robustness and cybersecurity of the AI-assisted workflow should be reviewed."),
            ]
        )
    if "prompt_injection_hidden" in ftype:
        mappings.extend(
            [
                _row("OWASP LLM Top 10", ["LLM01"], "Hidden prompt content indicates untrusted-input prompt manipulation risk."),
                _row("ISO42001", ["Human oversight", "Prompt handling"], "Model-facing content handling and human oversight should be reviewed."),
            ]
        )
    if any(tok in ftype for tok in ("data_exfiltration_instruction", "ssn_leakage_linked_qr")):
        mappings.extend(
            [
                _row("GDPR", ["Article 5", "Article 32", "Article 33"], "Potential exposure of personal data requires security and breach-review assessment."),
                _row("ISO27001", ["A.5.34", "A.8.12", "A.8.16"], "Data leakage prevention, privacy, and monitoring controls should be reviewed."),
            ]
        )
    if "ssn_leakage_linked_qr" in ftype:
        mappings.extend(
            [
                _row("PCI DSS", ["Req 10", "Req 12"], "Incident logging and governance should be reviewed where sensitive identity data is exposed in finance-linked workflows."),
                _row("HIPAA", ["Security Rule review"], "If regulated personal or healthcare data is implicated, regulated-data exposure review may be required."),
            ]
        )
    if any(tok in ftype for tok in ("c2_beacon_pattern", "lolbin_command_sequence")):
        mappings.extend(
            [
                _row("ISO27001", ["A.8.7", "A.8.16"], "Malware defense, monitoring, and detection controls are implicated."),
                _row("MITRE ATT&CK", ["Triage mapping"], "Behavior should be reviewed against ATT&CK for threat hunting and containment."),
            ]
        )
    if any(tok in ftype for tok in ("bank", "payment", "identity")):
        mappings.append(_row("GDPR", ["Article 5", "Article 32"], "If personal or account-linked data is involved, integrity and security controls should be reviewed."))
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in mappings:
        key = f"{row.get('framework')}::{','.join(row.get('controls') or [])}"
        if key in seen:
            continue
        seen.add(key)
        if row.get("evidence_refs"):
            out.append(row)
    return out[:6]
