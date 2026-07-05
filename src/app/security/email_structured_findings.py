"""Structured-findings builder + pre-agent-gate snapshot + agent-runs audit (extracted from
email_security.py, session 6).

Assembles the ranked, normalized structured findings + threat-hunter leads (_build_structured_
findings), the pre-agent gate snapshot, and the agent-runs audit that records which agents ran
under which boundaries. Composes the finding-level helpers from email_findings + the passive-payload
classifier + the maestro agent-action validator. No back-reference to email_security. Never raises.
Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Dict, List  # noqa: F401

from src.app.security.email_findings import (
    _email_agent_boundaries,
    _finding_source_toolset,
    _normalize_finding,
)
from src.app.security.maestro_boundaries import validate_agent_action
from src.app.security.passive_payload_analysis import classify_passive_payload


def _build_structured_findings(
    *,
    email: Dict[str, Any],
    verdict: Dict[str, Any],
    evidence_snapshot: Dict[str, Any],
    suggested_baseline_version: str | None = None,
) -> list[dict[str, Any]]:
    ev = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    findings: list[dict[str, Any]] = []
    suggested_action = str((verdict or {}).get("verdict_action") or "security_review")
    from_domain = str(email.get("vendor_domain") or "").strip().lower() or str(((ev.get("sender_infrastructure") or {}).get("sender_domain") or "")).strip().lower()
    auth = ev.get("auth_verdicts") if isinstance(ev.get("auth_verdicts"), dict) else {}
    infra = ev.get("sender_infrastructure") if isinstance(ev.get("sender_infrastructure"), dict) else {}
    attachment_rows = ev.get("attachment_forensics") if isinstance(ev.get("attachment_forensics"), list) else []
    diff_rows = ((ev.get("attachment_baseline_diffs") or {}).get("comparisons") if isinstance(ev.get("attachment_baseline_diffs"), dict) else []) or []
    verdict_indicators = [i for i in (verdict.get("indicators") or []) if isinstance(i, dict)]
    direct_attachment_rows = [
        item
        for item in attachment_rows
        if isinstance(item, dict) and str(item.get("attachment_class") or "") in {"active_payment_lure", "observed_supplier_artifact"}
    ]
    contextual_attachment_rows = [
        item
        for item in attachment_rows
        if isinstance(item, dict) and str(item.get("attachment_class") or "") in {"contextual_test_artifact", "reference_spec_material", "benign_reference_material"}
    ]

    if bool(auth.get("dmarc_fail")):
        findings.append(
            _normalize_finding(
                finding_id="sender_auth_dmarc_alignment_failed",
                finding_type="auth_failure_dmarc_alignment",
                summary="The sender failed DMARC alignment, so the platform could not trust the email identity.",
                severity_hint="high",
                confidence_score=0.94,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="sender_auth_agent",
                policy_weight=0.9,
                evidence=[f"SPF={auth.get('spf_result')}", f"DKIM={auth.get('dkim_result')}", f"DMARC={auth.get('dmarc_result')}"],
                retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or None},
                recommended_action=suggested_action,
            )
        )
    if bool(infra.get("reply_domain_mismatch")):
        findings.append(
            _normalize_finding(
                finding_id="sender_reply_domain_drift",
                finding_type="reply_drift",
                summary="The reply-to domain differs from the sender domain, which is a common supplier impersonation pattern.",
                severity_hint="high",
                confidence_score=0.89,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="sender_auth_agent",
                policy_weight=0.82,
                evidence=[f"sender_domain={infra.get('sender_domain')}", f"reply_domain={infra.get('reply_domain')}"],
                retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or None},
                recommended_action=suggested_action,
            )
        )
    if any(str((indicator or {}).get("type") or "") == "encoding_anomaly" for indicator in verdict_indicators):
        findings.append(
            _normalize_finding(
                finding_id="sender_message_hygiene_encoding_anomaly",
                finding_type="message_hygiene_encoding_anomaly",
                summary="The message contains encoding artifacts that weaken sender trust and read like repackaged or poorly copied content.",
                severity_hint="medium",
                confidence_score=0.66,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="sender_auth_agent",
                policy_weight=0.44,
                evidence=["subject/body contains mojibake or broken character encoding sequences"],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
            )
        )
    rep = (infra.get("reputation") if isinstance(infra.get("reputation"), dict) else {}) or {}
    if bool(rep.get("known_bad")) or bool((rep.get("flags") or [])):
        findings.append(
            _normalize_finding(
                finding_id="sender_infrastructure_anomaly",
                finding_type="infrastructure_anomaly",
                summary="The sending infrastructure shows anomalies or reputation flags that increase spoofing risk.",
                severity_hint="medium",
                confidence_score=0.77 if bool(rep.get("known_bad")) else 0.64,
                source_type="intel",
                evidence_kind="inferred",
                agent_origin="sender_auth_agent",
                policy_weight=0.55,
                evidence=[str(x) for x in (rep.get("flags") or [])][:5],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
            )
        )
    related = (infra.get("related_incidents") if isinstance(infra.get("related_incidents"), dict) else {}) or {}
    if int(related.get("count") or 0) > 0 and (direct_attachment_rows or not contextual_attachment_rows):
        observed_note = (
            "Observed supplier artifacts already support this overlap."
            if direct_attachment_rows
            else "This overlap exists without direct attachment evidence yet."
        )
        findings.append(
            _normalize_finding(
                finding_id="correlation_related_incidents",
                finding_type="related_incident_overlap",
                summary=f"The sender or infrastructure overlaps with {int(related.get('count') or 0)} prior incident(s). {observed_note}",
                severity_hint="medium",
                confidence_score=0.78 if direct_attachment_rows else 0.58,
                source_type="intel",
                evidence_kind="inferred",
                agent_origin="correlation_agent",
                policy_weight=0.52 if direct_attachment_rows else 0.28,
                evidence=([observed_note] + [f"{m.get('incident_id')} via {', '.join(m.get('match_on') or [])}" for m in (related.get("matches") or [])[:4] if isinstance(m, dict)])[:5],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
            )
        )

    for item in attachment_rows:
        if not isinstance(item, dict):
            continue
        fname = str(item.get("file_name") or "attachment")
        artifact_ref = {"file_name": fname, "sha256": str(item.get("sha256") or ""), "file_type": str(item.get("file_type") or "")}
        file_type = str(item.get("file_type") or "")
        inferred_source = "ocr" if file_type.startswith("image/") or "pdf" in file_type else "static"
        if bool(item.get("bank_fields_present")):
            bank_fields = item.get("bank_fields") if isinstance(item.get("bank_fields"), dict) else {}
            evidence = [f"{k}={v}" for k, v in list(bank_fields.items())[:4]]
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_bank_fields_{fname}",
                    finding_type="bank_detail_change",
                    summary=f"{fname} contains bank or remittance details that need independent verification.",
                    severity_hint="high",
                    confidence_score=0.92,
                    source_type=inferred_source,
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.88,
                    evidence=evidence or list(item.get("evidence_excerpt_lines") or [])[:3],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or None},
                    recommended_action=suggested_action,
                )
            )
        suspicious = [str(x) for x in (item.get("suspicious_instructions") or []) if str(x or "").strip()]
        if suspicious:
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_payment_change_{fname}",
                    finding_type="payment_change_request",
                    summary=f"{fname} requests changed payment or remittance handling.",
                    severity_hint="high",
                    confidence_score=0.87,
                    source_type=inferred_source,
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.84,
                    evidence=suspicious[:4] + list(item.get("evidence_excerpt_lines") or [])[:2],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None},
                    recommended_action=suggested_action,
                )
            )
        mismatch = [str(x) for x in (item.get("brand_supplier_mismatch_signals") or []) if str(x or "").strip()]
        if mismatch:
            findings.append(
                _normalize_finding(
                    finding_id=f"baseline_mismatch_{fname}",
                    finding_type="baseline_mismatch",
                    summary=f"{fname} does not line up with the trusted supplier baseline.",
                    severity_hint="high",
                    confidence_score=0.85,
                    source_type="baseline",
                    evidence_kind="inferred",
                    agent_origin="baseline_agent",
                    policy_weight=0.78,
                    evidence=mismatch[:4],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None, "baseline_version": suggested_baseline_version or "current"},
                    recommended_action=suggested_action,
                )
            )
        urls = [str(x) for x in (item.get("embedded_urls") or []) if str(x or "").strip()]
        if urls:
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_urls_{fname}",
                    finding_type="attachment_url_exposure",
                    summary=f"{fname} contains embedded URLs that should be checked before users act on the message.",
                    severity_hint="medium",
                    confidence_score=0.71,
                    source_type="static",
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.52,
                    evidence=urls[:4],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None},
                    recommended_action=suggested_action,
                )
            )
        qr_findings = [str(x) for x in (item.get("qr_redirect_findings") or []) if str(x or "").strip()]
        linked_artifact = dict(item.get("linked_artifact") or {}) if isinstance(item.get("linked_artifact"), dict) else {}
        if qr_findings:
            findings.append(
                _normalize_finding(
                    finding_id=f"attachment_qr_{fname}",
                    finding_type="qr_redirect_risk",
                    summary=f"{fname} contains a QR or redirect pattern that needs security review.",
                    severity_hint="medium",
                    confidence_score=0.8,
                    source_type="intel",
                    evidence_kind="direct",
                    agent_origin="attachment_forensics_agent",
                    policy_weight=0.66,
                    evidence=qr_findings[:4],
                    artifact_ref=artifact_ref,
                    retrieval_context={"supplier_domain": from_domain or None},
                    recommended_action=suggested_action,
                )
            )
        payload_analysis = classify_passive_payload(
            filename=fname,
            extracted_text=str(item.get("analysis_text_sample") or item.get("text_summary") or ""),
            signals={
                "qr_payloads": list(item.get("qr_payloads") or []) if isinstance(item.get("qr_payloads"), list) else [],
                "qr_prompt_injection": any("prompt" in q.lower() for q in qr_findings),
                "steg_suspicious": bool(((item.get("steg") or {}).get("suspicious"))),
                "steg_score": float(((item.get("steg") or {}).get("score") or 0.0) or 0.0),
                "steg_explanations": list(item.get("steg_explanations") or []) if isinstance(item.get("steg_explanations"), list) else [],
                "steg_details": dict(item.get("steg_details") or {}) if isinstance(item.get("steg_details"), dict) else {},
                "ssn_detected": bool(item.get("ssn_detected")),
                "pii_detected": bool(item.get("pii_detected")),
            },
        )
        matched_hypotheses = payload_analysis.get("matched_hypotheses") if isinstance(payload_analysis.get("matched_hypotheses"), list) else []
        if not matched_hypotheses:
            matched_hypotheses = [{"hypothesis": str(payload_analysis.get("attack_hypothesis") or "").strip().lower()}]
        hidden_mapping = {
            "lolbin_command_sequence": ("lolbin_command_sequence", "Hidden content describes a LOLBin command chain that could stage or execute payloads.", "behavioral", 0.91, 0.9),
            "c2_beacon": ("c2_beacon_pattern", "Hidden content resembles beacon or callback instructions linked to command-and-control behavior.", "behavioral", 0.89, 0.86),
            "data_exfiltration": ("data_exfiltration_instruction", "Hidden content describes how data could be collected or exfiltrated.", "behavioral", 0.9, 0.9),
            "prompt_injection": ("prompt_injection_hidden", "Hidden content appears designed to manipulate downstream AI or agent workflows.", "behavioral", 0.88, 0.82),
            "pii_data_exfil_via_qr": ("ssn_leakage_linked_qr", "A QR-linked or hidden path appears to expose SSNs or other sensitive identity data.", "intel", 0.93, 0.94),
            "macros": ("macro_auto_execution_lure", "The attachment contains macro auto-execution cues that warrant sandboxed runtime confirmation before trust is extended.", "behavioral", 0.84, 0.72),
        }
        emitted_types: set[str] = set()
        for matched_item in matched_hypotheses:
            if not isinstance(matched_item, dict):
                continue
            hypothesis = str(matched_item.get("hypothesis") or "").strip().lower()
            mapped = hidden_mapping.get(hypothesis)
            if not mapped:
                continue
            finding_type, summary, src_type, conf_score, policy_weight = mapped
            if finding_type in emitted_types:
                continue
            emitted_types.add(finding_type)
            payload_evidence = []
            payload_evidence.extend([str(x) for x in (item.get("steg_explanations") or []) if str(x or "").strip()][:2])
            payload_evidence.extend(list(item.get("evidence_excerpt_lines") or [])[:2])
            if hypothesis == "lolbin_command_sequence":
                payload_evidence.extend([str(x) for x in (payload_analysis.get("lolbin_hits") or []) if str(x or "").strip()][:3])
            payload_evidence.extend(qr_findings[:2])
            if hypothesis == "pii_data_exfil_via_qr" and linked_artifact:
                owner_scope = str(linked_artifact.get("linked_owner_scope") or "").strip()
                exposure_scope = str(linked_artifact.get("linked_exposure_scope") or "").strip()
                final_url = str(linked_artifact.get("linked_final_url") or "").strip()
                pii_types = [str(x) for x in (linked_artifact.get("pii_type") or []) if str(x or "").strip()]
                ssn_hits = list(linked_artifact.get("ssn_hits") or []) if isinstance(linked_artifact.get("ssn_hits"), list) else []
                if final_url:
                    payload_evidence.append(f"Linked destination: {final_url[:180]}")
                if pii_types:
                    payload_evidence.append(f"PII types detected: {', '.join(pii_types[:3])}")
                if ssn_hits:
                    payload_evidence.append(f"SSN pattern count: {len(ssn_hits)}")
                if owner_scope:
                    payload_evidence.append(f"Exposure owner scope: {owner_scope.replace('_', ' ')}")
                if exposure_scope:
                    payload_evidence.append(f"Exposure scope: {exposure_scope.replace('_', ' ')}")
            payload_evidence = [x for x in payload_evidence if x][:6]
            row = _normalize_finding(
                finding_id=f"{finding_type}_{fname}",
                finding_type=finding_type,
                summary=summary,
                severity_hint="high" if hypothesis not in {"prompt_injection", "macros"} else "medium",
                confidence_score=conf_score,
                source_type=src_type,
                evidence_kind="direct",
                agent_origin="attachment_forensics_agent",
                policy_weight=policy_weight,
                evidence=payload_evidence,
                artifact_ref=artifact_ref,
                retrieval_context={
                    "supplier_domain": from_domain or None,
                    "baseline_version": suggested_baseline_version or None,
                    "payload_type": payload_analysis.get("payload_type"),
                    "decode_path": matched_item.get("decode_path") or payload_analysis.get("decode_path"),
                    "linked_owner_scope": linked_artifact.get("linked_owner_scope") if linked_artifact else None,
                    "linked_exposure_scope": linked_artifact.get("linked_exposure_scope") if linked_artifact else None,
                    "linked_breach_severity_hint": linked_artifact.get("linked_breach_severity_hint") if linked_artifact else None,
                    "linked_human_verification_required": linked_artifact.get("linked_human_verification_required") if linked_artifact else None,
                },
                recommended_action=suggested_action,
            )
            row["claim_status"] = str(matched_item.get("claim_status") or row.get("claim_status") or "")
            row["finding_group"] = str(matched_item.get("finding_group") or row.get("finding_group") or "")
            row["evidence_lane"] = str(matched_item.get("evidence_lane") or "")
            row["mitre_attack"] = list(matched_item.get("mitre_attack") or payload_analysis.get("mitre_attack") or [])[:5]
            row["possible_mitre_attack"] = list(matched_item.get("possible_mitre_attack") or payload_analysis.get("possible_mitre_attack") or [])[:6]
            row["mitre_atlas"] = list(matched_item.get("mitre_atlas") or payload_analysis.get("mitre_atlas") or [])[:4]
            row["possible_mitre_atlas"] = list(matched_item.get("possible_mitre_atlas") or payload_analysis.get("possible_mitre_atlas") or [])[:4]
            row["payload_decode_path"] = str(matched_item.get("decode_path") or payload_analysis.get("decode_path") or "")
            row["pasta_stage"] = str(matched_item.get("pasta_stage") or payload_analysis.get("pasta_stage") or "")
            row["suggested_next_step"] = str(payload_analysis.get("suggested_next_step") or "")
            row["runtime_confirmation_required"] = bool(matched_item.get("runtime_confirmation_required"))
            row["runtime_evidence_required"] = list(matched_item.get("runtime_evidence_required") or payload_analysis.get("runtime_evidence_required") or [])[:6]
            row["lolbin_behavioral_profiles"] = list(payload_analysis.get("lolbin_behavioral_profiles") or [])[:4]
            binary_provenance = [dict(x) for x in (matched_item.get("binary_mitre_provenance") or payload_analysis.get("binary_mitre_provenance") or []) if isinstance(x, dict)][:8]
            row["binary_mitre_provenance"] = binary_provenance
            if binary_provenance:
                existing_refs = list(row.get("evidence_refs") or [])
                for bp in binary_provenance:
                    for ref in (bp.get("evidence_refs") or []):
                        ref_text = str(ref or "").strip()
                        if ref_text and ref_text not in existing_refs:
                            existing_refs.append(ref_text)
                row["evidence_refs"] = existing_refs[:12]
                artifact_rows = list(row.get("artifact_provenance") or [])
                for bp in binary_provenance:
                    refs = [str(x) for x in (bp.get("evidence_refs") or []) if str(x or "").strip()]
                    if not refs:
                        continue
                    artifact_rows.append({
                        "source_file": fname,
                        "extraction_method": "binary_attack_mapping",
                        "match_ref": refs[0],
                        "confidence": "medium",
                        "reason": str(bp.get("reason") or "").strip(),
                    })
                row["artifact_provenance"] = artifact_rows[:12]
            if linked_artifact:
                row["linked_artifact"] = linked_artifact
            findings.append(row)

    for item in diff_rows:
        if not isinstance(item, dict):
            continue
        differences = [str(x) for x in (item.get("differences") or []) if str(x or "").strip()]
        if not differences:
            continue
        findings.append(
            _normalize_finding(
                finding_id=f"attachment_drift_{item.get('candidate_file')}",
                finding_type="baseline_drift",
                summary=f"{item.get('candidate_file') or 'attachment'} drifted from the trusted baseline document.",
                severity_hint="high",
                confidence_score=0.83,
                source_type="baseline",
                evidence_kind="inferred",
                agent_origin="baseline_agent",
                policy_weight=0.74,
                evidence=differences[:4],
                artifact_ref={"file_name": str(item.get("candidate_file") or "")},
                retrieval_context={
                    "supplier_domain": from_domain or None,
                    "baseline_file": str(item.get("baseline_file") or ""),
                    "baseline_version": suggested_baseline_version or "current",
                },
                recommended_action=suggested_action,
            )
        )

    for reason in [str(x) for x in ((verdict or {}).get("reasons") or []) if str(x or "").strip()]:
        if reason not in {"oob_verification_required", "forced_reauth_required", "llm_policy_gate_denied", "artifact_risk_block_band", "artifact_risk_review_band"}:
            continue
        findings.append(
            _normalize_finding(
                finding_id=f"policy_reason_{reason}",
                finding_type="policy_violation",
                summary=str(reason).replace("_", " "),
                severity_hint="medium" if "review" in reason else "high",
                confidence_score=0.76 if "review" in reason else 0.86,
                source_type="policy",
                evidence_kind="direct",
                agent_origin="playbook_agent",
                policy_weight=0.8,
                evidence=[reason],
                retrieval_context={"supplier_domain": from_domain or None},
                recommended_action=suggested_action,
                allowed_actions=["notify_analyst", "create_ticket", "security_review"],
                disallowed_actions=["approve_supplier_update", "push_block_rule", "approve_payment_change"],
            )
        )
    return findings


def _build_pre_agent_gate_snapshot(
    *,
    ingest_gate_meta: Dict[str, Any] | None,
    ocr_sanitization_meta: Dict[str, Any] | None,
    llm_controls: Dict[str, Any] | None,
) -> Dict[str, Any]:
    ingest = ingest_gate_meta if isinstance(ingest_gate_meta, dict) else {}
    ocr = ocr_sanitization_meta if isinstance(ocr_sanitization_meta, dict) else {}
    llm = llm_controls if isinstance(llm_controls, dict) else {}
    return {
        "artifact_text_untrusted": True,
        "ocr_text_sanitized": True,
        "sandbox_required": bool(llm.get("sandbox_required", True)),
        "blocked_qr_url_count": int(ocr.get("blocked_qr_url_count") or 0),
        "blocked_attachment_count": int(ingest.get("blocked_count") or 0),
        "blocked_attachment_reasons": [str(x) for x in (ingest.get("block_reasons") or []) if str(x or "").strip()][:8],
        "blocked_tool_intents": [str(x) for x in (llm.get("blocked_intents") or []) if str(x or "").strip()][:8],
        "allow_tools": [str(x) for x in (llm.get("allow_tools") or []) if str(x or "").strip()][:8],
    }


def _build_agent_runs_audit(
    *,
    evidence_snapshot: Dict[str, Any],
    structured_findings: list[dict[str, Any]],
    policy_gate: Dict[str, Any] | None,
) -> list[dict[str, Any]]:
    ev = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    findings = [f for f in structured_findings if isinstance(f, dict)]
    boundaries = _email_agent_boundaries()
    scope_map = {
        "sender_auth_agent": "headers",
        "attachment_forensics_agent": "attachments",
        "baseline_agent": "suppliers",
        "correlation_agent": "security_events",
        "explanation_agent": "policies",
        "playbook_agent": "policies",
    }

    def _count(agent_name: str) -> int:
        return sum(1 for f in findings if str(f.get("agent_origin") or "") == agent_name)

    auth = ev.get("auth_verdicts") if isinstance(ev.get("auth_verdicts"), dict) else {}
    infra = ev.get("sender_infrastructure") if isinstance(ev.get("sender_infrastructure"), dict) else {}
    atts = ev.get("attachment_forensics") if isinstance(ev.get("attachment_forensics"), list) else []
    rel = (infra.get("related_incidents") if isinstance(infra.get("related_incidents"), dict) else {}) or {}
    playbook = ev.get("playbook_run") if isinstance(ev.get("playbook_run"), dict) else {}
    route_after = str((policy_gate or {}).get("decision") or ev.get("route") or "review")
    runs: list[dict[str, Any]] = []
    parallel_agent_ids = [row[0] for row in [
        ("sender_auth_agent", {}),
        ("attachment_forensics_agent", {}),
        ("baseline_agent", {}),
        ("correlation_agent", {}),
        ("explanation_agent", {}),
        ("playbook_agent", {}),
    ]]
    rows = [
        (
            "sender_auth_agent",
            {
                "inputs_used": ["message_headers", "spf_dkim_dmarc", "header_forensics"],
                "input_refs": [k for k in ("spf_result", "dkim_result", "dmarc_result") if auth.get(k) is not None] + ([infra.get("sender_domain")] if infra.get("sender_domain") else []),
                "confidence": 0.88 if _count("sender_auth_agent") else 0.52,
                "why_ran": "Email headers and sender identity signals were present and required authentication review.",
                "output_quality": "structural",
            },
        ),
        (
            "attachment_forensics_agent",
            {
                "inputs_used": ["sanitized_attachment_text", "ocr_output", "file_metadata", "static_analysis"],
                "input_refs": [str(a.get("file_name") or "") for a in atts[:8] if isinstance(a, dict)],
                "confidence": 0.86 if _count("attachment_forensics_agent") else 0.5,
                "why_ran": "Attachments were present and needed passive extraction, OCR, and static analysis.",
                "output_quality": "structural",
            },
        ),
        (
            "baseline_agent",
            {
                "inputs_used": ["supplier_profile", "approved_contacts", "bank_fingerprints", "template_hashes"],
                "input_refs": [str(((ev.get("attachment_baseline_diffs") or {}).get("baseline_file") or ""))] if isinstance(ev.get("attachment_baseline_diffs"), dict) else [],
                "confidence": 0.84 if _count("baseline_agent") else 0.5,
                "why_ran": "Supplier and template baseline checks were available for comparison.",
                "output_quality": "structural",
            },
        ),
        (
            "correlation_agent",
            {
                "inputs_used": ["prior_incidents", "sender_domain", "reply_domain", "incident_graph"],
                "input_refs": [str(m.get("incident_id") or "") for m in (rel.get("matches") or [])[:5] if isinstance(m, dict)],
                "confidence": 0.72 if _count("correlation_agent") else 0.46,
                "why_ran": "Related incident and infrastructure overlap checks were available.",
                "output_quality": "structural",
            },
        ),
        (
            "explanation_agent",
            {
                "inputs_used": ["normalized_findings", "faq_policy_mappings", "business_impact_model"],
                "input_refs": [str(f.get("finding_id") or "") for f in findings[:5]],
                "confidence": 0.78 if findings else 0.45,
                "why_ran": "A human-readable explanation was required after evidence normalization.",
                "output_quality": "heuristic",
            },
        ),
        (
            "playbook_agent",
            {
                "inputs_used": ["policy_approved_findings", "allowed_actions", "sop_mappings"],
                "input_refs": [str(playbook.get("playbook_id") or "")] if playbook else [],
                "confidence": 0.81 if _count("playbook_agent") else 0.49,
                "why_ran": "Response playbook selection was required after verdict routing.",
                "output_quality": "structural",
            },
        ),
    ]
    for agent_name, meta in rows:
        boundary = boundaries.get(agent_name) or {}
        violations = []
        for tool_name in _finding_source_toolset(agent_name):
            violations.extend(
                [
                    {
                        "violation_type": v.violation_type,
                        "detail": v.detail,
                        "severity": v.severity,
                    }
                    for v in validate_agent_action(agent_name=agent_name, tool_name=tool_name)
                ]
            )
        scope_name = str(scope_map.get(agent_name) or "").strip()
        if scope_name:
            violations.extend(
                [
                    {
                        "violation_type": v.violation_type,
                        "detail": v.detail,
                        "severity": v.severity,
                    }
                    for v in validate_agent_action(agent_name=agent_name, data_scope=scope_name)
                ]
            )
        agent_findings = [f for f in findings if str(f.get("agent_origin") or "") == agent_name]
        evidence_added = [str(f.get("finding_id") or f.get("finding_type") or "") for f in agent_findings[:8] if str(f.get("finding_id") or f.get("finding_type") or "").strip()]
        runs.append(
            {
                "agent_name": agent_name,
                "agent_id": agent_name,
                "scope_enforced": len(violations) == 0,
                "allowed_inputs": list(boundary.get("allowed_inputs") or []),
                "allowed_tools": list(boundary.get("allowed_tools") or []),
                "allowed_outputs": list(boundary.get("allowed_outputs") or []),
                "denied_capabilities": list(boundary.get("denied_capabilities") or []),
                "inputs_used": list(meta.get("inputs_used") or []),
                "input_refs": [str(x) for x in (meta.get("input_refs") or []) if str(x or "").strip()][:8],
                "input_summary": ", ".join([str(x) for x in (meta.get("input_refs") or []) if str(x or "").strip()][:4]) or ", ".join(meta.get("inputs_used") or []),
                "tools_used": _finding_source_toolset(agent_name),
                "output_count": _count(agent_name),
                "confidence": round(float(meta.get("confidence") or 0.0), 4),
                "why_ran": str(meta.get("why_ran") or ""),
                "evidence_added": evidence_added,
                "evidence_retracted": [],
                "verdict_before": "review" if agent_name in {"explanation_agent", "playbook_agent"} else "allow",
                "verdict_after": route_after,
                "confidence_delta": round(float(meta.get("confidence") or 0.0) - 0.45, 3),
                "output_quality": str(meta.get("output_quality") or "heuristic"),
                "ran_in_parallel_with": [name for name in parallel_agent_ids if name != agent_name],
                "filler_suppressed": True,
                "policy_result": str((policy_gate or {}).get("decision") or "allow"),
                "actions_taken": [],
                "scope_violations": violations[:10],
                "trace_id": str(ev.get("trace_id") or ev.get("decision_id") or ""),
            }
        )
    return runs
