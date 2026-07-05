"""Business-bundle + hidden-payload drilldown + structured-finding decoration (extracted from
email_security.py, session 4).

Turns raw findings into the operator-facing business bundle (impact/why/next-step), the drilldown
for a hidden payload, and decorates structured findings. Pure over finding dicts; the finding-level
helpers it composes live in email_findings (session 3) — imported directly, no back-reference to
email_security. Never raises. Vertical-blind.
"""
from __future__ import annotations

from typing import Any, Dict, List  # noqa: F401

from src.app.security.email_findings import (
    _artifact_evidence_refs,
    _artifact_finding_category,
    _artifact_provenance_rows,
    _claim_contract_for_finding,
    _finding_agentic_tags,
    _finding_compliance_mapping,
)


def _hidden_payload_drilldown(
    finding_type: str,
    threat_context: Dict[str, Any],
) -> Dict[str, Any] | None:
    ftype = str(finding_type or "").lower()
    if "lolbin_command_sequence" in ftype:
        return {
            "headline": "Hidden LOLBin execution chain detected",
            "business_risk": "Trusted admin tools may be abused to download or launch attacker payloads while blending into normal operations.",
            "affected_scope": "Potentially affected users are those who opened or processed the artifact and any workstation that executed the hidden chain.",
            "forensic_checks": [
                "Review PowerShell, certutil, mshta, rundll32, regsvr32, bitsadmin, wscript, and cscript process launches.",
                "Check parent-child process chains, download destinations, and recently written payload files.",
                "Correlate endpoint events with proxy, DNS, and EDR telemetry for the same user and host.",
            ],
            "hunt_queries": [
                "Search EDR for LOLBin executions and encoded-command usage in the incident window.",
                "Review outbound fetches, payload URLs, and new binaries written after the artifact was handled.",
            ],
            "crisis_actions": ["No public statement is usually needed unless execution or downstream impact is confirmed."],
            "threat_context": threat_context,
        }
    if "c2_beacon_pattern" in ftype:
        return {
            "headline": "Hidden beacon or callback pattern detected",
            "business_risk": "An attacker may be trying to keep a foothold and request further instructions from external infrastructure.",
            "affected_scope": "Potentially affected hosts are any systems that opened the artifact or show the same callback pattern in telemetry.",
            "forensic_checks": [
                "Review DNS, proxy, firewall, and EDR telemetry for repeated low-volume callbacks, jitter, or periodic requests.",
                "Check for HTTP(S), DNS tunneling, or uncommon destinations that match extracted callback indicators.",
                "Review service persistence, scheduled tasks, and repeated process network connections.",
            ],
            "hunt_queries": [
                "Search network telemetry for repeated small packets, callback intervals, and low-volume periodic traffic.",
                "Look for the same user, process, or host contacting the destination after artifact handling.",
            ],
            "crisis_actions": ["No public statement unless confirmed compromise or service impact is found."],
            "threat_context": threat_context,
        }
    if "data_exfiltration_instruction" in ftype:
        return {
            "headline": "Hidden exfiltration instructions detected",
            "business_risk": "The content appears designed to steal data rather than merely trick a user.",
            "affected_scope": "Potentially affected accounts are those that opened the artifact or had access to the data sources named in follow-on telemetry.",
            "forensic_checks": [
                "Review archive creation, compression tools, staging directories, and cloud-sync or upload activity.",
                "Check identity logs, file access logs, eBPF or EDR events, browser uploads, and outbound transfers.",
                "Determine what repositories were reachable from the affected account and whether those files were copied or moved.",
            ],
            "hunt_queries": [
                "Search for zip, rclone, scp, curl, wget, browser upload, or cloud-storage transfer activity after artifact interaction.",
                "Correlate identity, endpoint, proxy, and storage access logs to estimate what was reachable and what was actually moved.",
            ],
            "crisis_actions": ["Prepare breach-communication inputs only if exposure is confirmed; instructions alone are not proof of exfiltration."],
            "threat_context": threat_context,
        }
    if "prompt_injection_hidden" in ftype:
        return {
            "headline": "Hidden prompt-injection content detected",
            "business_risk": "This threatens AI reliability, decision integrity, and downstream automation rather than just a single endpoint.",
            "affected_scope": "Affected systems are any model, agent, or workflow that ingested the hidden text via QR, steganography, OCR overlay, or document extraction.",
            "forensic_checks": [
                "Verify the artifact was sanitized before any model-facing use.",
                "Review agent audit logs for tool requests, context leakage, or abnormal instructions after ingestion.",
                "Classify the carrier as QR, steganography, text overlay, or extracted document text for root-cause analysis.",
            ],
            "hunt_queries": [
                "Search model and agent logs for hidden-instruction strings, tool-use spikes, or unsafe action requests tied to the artifact.",
            ],
            "crisis_actions": ["This is usually an internal AI-governance issue unless it caused a confirmed data leak or customer impact."],
            "threat_context": threat_context,
        }
    if "ssn_leakage_linked_qr" in ftype:
        return {
            "headline": "Linked QR path suggests SSN or regulated identity leakage",
            "business_risk": "Potential privacy-reporting, reputational, and customer-trust impact if the exposure is confirmed.",
            "affected_scope": "Potentially affected users are the people whose identity records were accessible through the linked content.",
            "forensic_checks": [
                "Review the linked content, access-control path, and publication workflow that exposed the data.",
                "Check whether RBAC, ABAC, object permissions, or public-link controls failed.",
                "Capture URL, access logs, GeoIP, referrers, and object-access records to estimate scope and timeline.",
            ],
            "hunt_queries": [
                "Search access logs for unusual countries, hosting ASN traffic, and repeated fetches to the exposed artifact.",
                "Look for insider, supplier, or public-link misuse patterns before concluding attacker origin.",
            ],
            "crisis_actions": [
                "Engage privacy, legal, and communications leads early.",
                "Prepare holding statements and risk-register updates for brand, regulatory, and customer impact.",
            ],
            "threat_context": threat_context,
        }
    return None


def _finding_business_bundle(
    *,
    finding_type: str,
    category: str,
    source_type: str,
    evidence: list[str],
    threat: Dict[str, Any] | None,
) -> Dict[str, Any]:
    ftype = str(finding_type or "").lower()
    cat = str(category or "").lower()
    src = str(source_type or "").lower()
    dread = (threat.get("dread") if isinstance(threat, dict) and isinstance(threat.get("dread"), dict) else {}) or {}
    pasta_stage = str((threat or {}).get("pasta_stage") or "").strip()
    mitre_attack = list((threat or {}).get("mitre_attack") or []) if isinstance(threat, dict) else []
    owasp = list((threat or {}).get("owasp_llm_top10") or []) if isinstance(threat, dict) else []
    threat_context = {
        "pasta_stage": pasta_stage,
        "dread": dread,
        "mitre_attack": mitre_attack[:4],
        "owasp_llm_top10": owasp[:4],
        "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
    }
    hidden_drilldown = _hidden_payload_drilldown(ftype, threat_context)
    if hidden_drilldown:
        if "lolbin_command_sequence" in ftype:
            return {
                "business_meaning": "A hidden command sequence appears to abuse trusted operating-system tools to fetch or run payloads without using obvious malware binaries.",
                "business_outcome": "A user or endpoint could be turned into a launch point for malware, follow-on payloads, or lateral movement using tools defenders often allow by default.",
                "next_steps": [
                    "Contain the related host or user workflow before allowing execution.",
                    "Hunt for LOLBin process launches, downloads, and child-process chains on the same endpoint.",
                    "Queue sandbox review for the extracted command path and any downloaded payload.",
                ],
                "policy_mapping": ["sandbox_required_for_hidden_command_payloads", "endpoint_containment_on_lolbin_chain"],
                "faq_mapping": ["How to investigate LOLBin abuse", "What to do when an image hides a command sequence"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        if "c2_beacon_pattern" in ftype:
            return {
                "business_meaning": "The hidden payload looks like command-and-control beaconing rather than a normal business image or document.",
                "business_outcome": "If the pattern was executed, an endpoint may be checking in to attacker infrastructure for follow-on commands.",
                "next_steps": [
                    "Contain the potentially affected host and confirm whether any payload from the hidden content executed.",
                    "Give hunters the callback hints, interval, and destination clues for network and XDR review.",
                    "Escalate to incident response if endpoint, DNS, or proxy telemetry confirms matching check-ins.",
                ],
                "policy_mapping": ["threat_hunt_required_for_hidden_c2_pattern", "containment_on_confirmed_beacon_overlap"],
                "faq_mapping": ["How to investigate possible command-and-control beaconing"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        if "data_exfiltration_instruction" in ftype:
            return {
                "business_meaning": "The hidden content describes how data should be collected and moved out of the environment.",
                "business_outcome": "Sensitive files, customer data, credentials, or internal documents could be targeted for theft if an endpoint or user followed the embedded instructions.",
                "next_steps": [
                    "Pause the workflow, contain the affected account or host, and review whether any collection or upload activity occurred.",
                    "Check endpoint, eBPF, EDR, proxy, and identity telemetry for archive creation, staging, and outbound transfer attempts.",
                    "Escalate for breach assessment if sensitive data stores, cloud buckets, or customer records were in scope.",
                ],
                "policy_mapping": ["data_exfiltration_ir_required", "sensitive_data_hunt_required"],
                "faq_mapping": ["How to investigate suspected data exfiltration", "What evidence to collect for a possible data leak"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        if "prompt_injection_hidden" in ftype:
            return {
                "business_meaning": "The hidden content tries to manipulate AI or agent workflows rather than only human readers.",
                "business_outcome": "If model-facing controls are weak, the hidden instructions could steer assistants, leak context, or weaken decision quality.",
                "next_steps": [
                    "Confirm the prompt-injection guardrails held and that the artifact text was treated as untrusted.",
                    "Review whether any AI-assisted workflow saw the hidden content before sanitization.",
                    "Use human review before allowing the artifact into automated agent chains or retrieval corpora.",
                ],
                "policy_mapping": ["llm_artifact_text_untrusted", "human_review_required_for_hidden_prompt_content"],
                "faq_mapping": ["How the platform handles hidden prompt injection", "What to do when an attachment targets AI workflows"],
                "threat_context": threat_context,
                "drilldown": hidden_drilldown,
            }
        return {
            "business_meaning": "A QR-linked path appears to expose Social Security or similarly sensitive identity data.",
            "business_outcome": "This could become a customer-trust, privacy, legal, and brand-damage event if the exposure is real and tied to regulated data handling failures.",
            "next_steps": [
                "Treat the linked content as a potential regulated-data incident and start privacy and security review immediately.",
                "Determine whether the exposure came from a supplier, insider misuse, broken access control, or compromised public content.",
                "Prepare customer-notification, legal, and communications inputs if exposure is confirmed.",
            ],
            "policy_mapping": ["regulated_data_incident_review_required", "public_content_pii_exposure_escalation"],
            "faq_mapping": ["What to do when SSNs or regulated identity data may be exposed", "How to coordinate privacy, legal, and PR teams"],
            "threat_context": threat_context,
            "drilldown": hidden_drilldown,
        }
    if "bank_detail" in ftype or "payment_change" in ftype:
        return {
            "business_meaning": "The message is trying to influence how money is sent or where it is sent.",
            "business_outcome": "If staff trust this request, the business could send payment to the wrong account.",
            "next_steps": [
                "Hold any payment or supplier-detail change linked to this message.",
                "Verify the request through an approved callback channel.",
                "Record the supplier and bank details in the incident for finance review.",
            ],
            "policy_mapping": ["supplier_bank_change_requires_oob_callback", "finance_payment_hold_on_unverified_change"],
            "faq_mapping": ["How to verify a supplier bank change", "What to do when payment details change by email"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if "baseline" in ftype or cat == "baseline_drift":
        return {
            "business_meaning": "The document does not look like the supplier documents the business normally trusts.",
            "business_outcome": "This increases the chance of supplier impersonation, invoice tampering, or account-compromise fraud.",
            "next_steps": [
                "Compare this document against the trusted supplier baseline before approving it.",
                "Check for bank-detail, logo, or remittance block changes.",
                "Escalate to finance or supplier-risk review if the drift cannot be explained.",
            ],
            "policy_mapping": ["supplier_baseline_review_required"],
            "faq_mapping": ["How to compare a supplier invoice to the trusted baseline"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if "reply_drift" in ftype or "auth_failure" in ftype or "infrastructure" in ftype:
        return {
            "business_meaning": "The sender identity or sending path does not line up with what the business should expect from this supplier.",
            "business_outcome": "Staff could trust a spoofed or compromised sender and act on fraudulent instructions.",
            "next_steps": [
                "Do not trust the sender address alone.",
                "Verify the supplier using a known-good contact path.",
                "Treat the email as suspicious until identity checks are resolved.",
            ],
            "policy_mapping": ["sender_identity_verification_required"],
            "faq_mapping": ["How to verify a suspicious supplier email"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if "encoding_anomaly" in ftype or "message_hygiene" in ftype:
        return {
            "business_meaning": "The message looks poorly encoded or repackaged, which weakens trust in how it was produced and delivered.",
            "business_outcome": "This is not proof of fraud by itself, but it strengthens the case that the message is not a normal supplier communication.",
            "next_steps": [
                "Treat the message as suspicious until sender identity and document evidence are resolved.",
                "Use this as supporting context behind stronger payment, document, or sender findings.",
            ],
            "policy_mapping": ["message_hygiene_supporting_signal_only"],
            "faq_mapping": ["How to interpret message hygiene and encoding anomalies"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "contextual_test_artifact":
        return {
            "business_meaning": "This file looks like test, lab, or reference material rather than a live supplier artifact.",
            "business_outcome": "It can explain why the platform is suspicious, but it should not outweigh direct fraud evidence from live attachments or sender identity.",
            "next_steps": [
                "Use this file as supporting context, not the primary reason for a fraud verdict.",
                "Prioritize real invoices, PDFs, images, sender trust, and bank-change evidence first.",
            ],
            "policy_mapping": ["contextual_test_artifact_non_authoritative"],
            "faq_mapping": ["How the platform treats test fixtures and reference material"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "reference_spec_material":
        return {
            "business_meaning": "This file reads like specification, scenario, or test reference material rather than a live business artifact.",
            "business_outcome": "It provides context for why the platform is cautious, but it should stay behind direct evidence from real invoices, images, or sender checks.",
            "next_steps": [
                "Keep this file as supporting context only.",
                "Prioritize live supplier documents, sender identity, and direct payment-change evidence before acting.",
            ],
            "policy_mapping": ["reference_spec_material_non_authoritative"],
            "faq_mapping": ["How the platform treats specifications, scenarios, and testing guides"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "benign_reference_material":
        return {
            "business_meaning": "This file looks more like reference or test material than a real supplier artifact.",
            "business_outcome": "It may still contain useful fraud indicators, but it should not outweigh direct supplier-fraud evidence.",
            "next_steps": [
                "Treat the file as context, not the primary reason for the verdict.",
                "Prioritize actual supplier documents, sender identity, and payment-change evidence first.",
            ],
            "policy_mapping": ["reference_material_non_authoritative"],
            "faq_mapping": ["How the platform ranks reference material vs direct fraud evidence"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    if cat == "contradicts_sender_claim":
        return {
            "business_meaning": "This file does not support the sender’s story and may contradict what the business expects from the supplier.",
            "business_outcome": "That increases the likelihood of impersonation, account compromise, or document tampering.",
            "next_steps": [
                "Validate the sender claim against supplier history and approved templates.",
                "Review whether the document content matches the business request it arrived with.",
            ],
            "policy_mapping": ["supplier_claim_consistency_review_required"],
            "faq_mapping": ["How to handle a document that contradicts the supplier story"],
            "threat_context": {
                "pasta_stage": pasta_stage,
                "dread": dread,
                "mitre_attack": mitre_attack[:4],
                "owasp_llm_top10": owasp[:4],
                "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
            },
        }
    return {
        "business_meaning": "The platform found evidence that this message may not be safe to trust without review.",
        "business_outcome": "Acting too quickly could create financial loss, account risk, or investigation overhead.",
        "next_steps": [
            "Pause business action on the message until the strongest findings are reviewed.",
            "Use the ranked evidence to verify sender identity and attachment intent.",
        ],
        "policy_mapping": ["security_review_required"],
        "faq_mapping": ["What to do when an email is sent to security review"],
        "threat_context": {
            "pasta_stage": pasta_stage,
            "dread": dread,
            "mitre_attack": mitre_attack[:4],
            "owasp_llm_top10": owasp[:4],
            "agentic_ai_top10": _finding_agentic_tags(ftype, src, cat),
        },
    }


def _decorate_structured_findings(
    *,
    findings: list[dict[str, Any]],
    evidence_snapshot: Dict[str, Any],
) -> list[dict[str, Any]]:
    ev = evidence_snapshot if isinstance(evidence_snapshot, dict) else {}
    threat = ev.get("threat_correlation") if isinstance(ev.get("threat_correlation"), dict) else {}
    attachment_rows = ev.get("attachment_forensics") if isinstance(ev.get("attachment_forensics"), list) else []

    def _attachment_row(filename: str) -> dict[str, Any]:
        for item in attachment_rows:
            if isinstance(item, dict) and str(item.get("file_name") or "").strip() == filename:
                return item
        return {}

    out: list[dict[str, Any]] = []
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        row = dict(finding)
        filename = str(((row.get("artifact_ref") or {}).get("file_name") or "")).strip()
        attachment = _attachment_row(filename)
        category = _artifact_finding_category(filename, str(row.get("finding_type") or ""), str(row.get("summary") or ""))
        claim_status, finding_group = _claim_contract_for_finding(
            filename=filename,
            finding_type=str(row.get("finding_type") or ""),
            evidence_kind=str(row.get("evidence_kind") or ""),
            category=category,
            source_type=str(row.get("source_type") or ""),
            extracted_text=str((attachment.get("analysis_text_sample") or attachment.get("text_summary") or "") if isinstance(attachment, dict) else ""),
            evidence=[str(x) for x in (row.get("evidence") or []) if str(x or "").strip()],
        )
        row["finding_category"] = category
        row["claim_status"] = claim_status
        row["finding_group"] = finding_group
        provenance_text = [str(x) for x in (row.get("evidence") or []) if str(x or "").strip()]
        attachment_text = str((attachment.get("analysis_text_sample") or attachment.get("text_summary") or "") if isinstance(attachment, dict) else "")
        if attachment_text:
            provenance_text.append(attachment_text)
        if not row.get("evidence_refs"):
            row["evidence_refs"] = _artifact_evidence_refs(filename, provenance_text)
        if not row.get("artifact_provenance"):
            row["artifact_provenance"] = _artifact_provenance_rows(
                filename=filename,
                evidence=provenance_text,
                file_type=str(((row.get("artifact_ref") or {}).get("file_type") or attachment.get("file_type") or "")),
                claim_status=claim_status,
            )
        if not row.get("evidence_refs") and not row.get("artifact_provenance"):
            row["claim_status"] = "suppressed"
            row["finding_group"] = "detection_artifact_patterns"
            row["suppressed_reason"] = "missing_visible_provenance"
        bundle = _finding_business_bundle(
            finding_type=str(row.get("finding_type") or ""),
            category=category,
            source_type=str(row.get("source_type") or ""),
            evidence=[str(x) for x in (row.get("evidence") or []) if str(x or "").strip()],
            threat=threat if isinstance(threat, dict) else {},
        )
        row["business_meaning"] = bundle.get("business_meaning")
        row["business_outcome"] = bundle.get("business_outcome")
        row["next_steps"] = list(bundle.get("next_steps") or [])
        row["policy_mapping"] = list(bundle.get("policy_mapping") or [])
        row["faq_mapping"] = list(bundle.get("faq_mapping") or [])
        row["threat_context"] = dict(bundle.get("threat_context") or {})
        if str(row.get("pasta_stage") or "").strip():
            row["threat_context"]["pasta_stage"] = str(row.get("pasta_stage") or "").strip()
        if isinstance(row.get("mitre_attack"), list) and row.get("mitre_attack"):
            row["threat_context"]["mitre_attack"] = list(row.get("mitre_attack") or [])[:5]
        row["drilldown"] = dict(bundle.get("drilldown") or {}) if isinstance(bundle.get("drilldown"), dict) else {}
        if str(row.get("finding_type") or "") == "ssn_leakage_linked_qr":
            linked = row.get("linked_artifact") if isinstance(row.get("linked_artifact"), dict) else {}
            retrieval = row.get("retrieval_context") if isinstance(row.get("retrieval_context"), dict) else {}
            owner_scope = str((linked.get("linked_owner_scope") or retrieval.get("linked_owner_scope") or "")).strip()
            exposure_scope = str((linked.get("linked_exposure_scope") or retrieval.get("linked_exposure_scope") or "")).strip()
            owner_reason = str(linked.get("linked_owner_reason") or "").strip()
            final_url = str(linked.get("linked_final_url") or "").strip()
            pii_types = [str(x) for x in (linked.get("pii_type") or []) if str(x or "").strip()]
            ssn_hits = list(linked.get("ssn_hits") or []) if isinstance(linked.get("ssn_hits"), list) else []
            privacy_scope_lines = []
            if owner_scope:
                privacy_scope_lines.append(f"Owner scope: {owner_scope.replace('_', ' ')}")
            if exposure_scope:
                privacy_scope_lines.append(f"Exposure scope: {exposure_scope.replace('_', ' ')}")
            if owner_reason:
                privacy_scope_lines.append(owner_reason)
            if pii_types:
                privacy_scope_lines.append(f"PII types: {', '.join(pii_types[:3])}")
            if ssn_hits:
                privacy_scope_lines.append(f"SSN pattern count: {len(ssn_hits)}")
            if final_url:
                privacy_scope_lines.append(f"Linked destination: {final_url[:180]}")
            if privacy_scope_lines:
                row["drilldown"]["privacy_scope"] = privacy_scope_lines
            if bool(linked.get("linked_human_verification_required") or retrieval.get("linked_human_verification_required")):
                row["drilldown"]["human_verification"] = [
                    "Confirm whether the linked content belongs to the platform, a supplier, or a third party before declaring breach scope.",
                    "Verify access-control posture, audience, and actual access logs before claiming confirmed exposure.",
                ]
        row["compliance_mapping"] = _finding_compliance_mapping(
            finding_type=str(row.get("finding_type") or ""),
            category=category,
            source_type=str(row.get("source_type") or ""),
            evidence=[str(x) for x in (row.get("evidence") or []) if str(x or "").strip()],
            business_outcome=str(row.get("business_outcome") or ""),
            claim_status=claim_status,
        )
        out.append(row)
    return out
