from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.app.security.control_registry import get_control_record, get_control_registry_version
from src.app.security.owasp_map import map_signals_to_owasp

_FRAMEWORK_MAPPING_VERSION = "2026.03.28.1"
_VALID_KILL_CHAIN_STAGES = {
    "Reconnaissance",
    "Weaponization",
    "Delivery",
    "Exploitation",
    "Installation",
    "CommandAndControl",
    "ActionsOnObjectives",
}
_VALID_PASTA_STAGE_NAMES = {
    "DefineObjectives",
    "DefineTechnicalScope",
    "ApplicationDecomposition",
    "ThreatAnalysis",
    "VulnerabilityAnalysis",
    "ModellingAndSimulation",
    "RiskAndImpactAnalysis",
}
_CONTROL_NAME_CATALOG: Dict[str, Dict[str, str]] = {
    "MITRE ATT&CK": {
        "T1566.001": "Spearphishing Attachment",
        "T1566.002": "Spearphishing Link",
        "T1199": "Trusted Relationship",
        "T1589": "Gather Victim Identity Information",
        "T1565": "Data Manipulation",
        "T1078": "Valid Accounts",
        "T1218.003": "System Binary Proxy Execution: CMSTP",
        "T1105": "Ingress Tool Transfer",
        "T1140": "Deobfuscate/Decode Files or Information",
        "T1047": "Windows Management Instrumentation",
        "T1202": "Indirect Command Execution",
        "T1218.005": "System Binary Proxy Execution: Mshta",
        "T1218.007": "System Binary Proxy Execution: Msiexec",
        "T1218.010": "System Binary Proxy Execution: Regsvr32",
        "T1218.011": "System Binary Proxy Execution: Rundll32",
        "T1059.001": "Command and Scripting Interpreter: PowerShell",
        "T1059.003": "Command and Scripting Interpreter: Windows Command Shell",
        "T1059.005": "Command and Scripting Interpreter: Visual Basic",
        "T1197": "BITS Jobs",
        "T1053.005": "Scheduled Task/Job: Scheduled Task",
        "T1048.003": "Exfiltration Over Alternative Protocol: Exfiltration Over Unencrypted/Obfuscated Non-C2 Protocol",
        "T1105": "Ingress Tool Transfer",
        "T1071.001": "Application Layer Protocol: Web Protocols",
        "T1071.004": "Application Layer Protocol: DNS",
        "T1573.002": "Encrypted Channel: Asymmetric Cryptography",
        "T1203": "Exploitation for Client Execution",
        "T1029": "Scheduled Transfer",
        "T1041": "Exfiltration Over C2 Channel",
    },
    "MITRE ATLAS": {
        "AML.T0043": "Craft Adversarial Data",
        "AML.T0051": "Prompt Injection",
        "AML.T0048": "Discover ML Artifacts",
        "AML.T0040": "ML Supply Chain Compromise",
    },
    "ISO27001": {
        "A.5.16": "Identity management",
        "A.5.17": "Authentication information",
        "A.5.19": "Information security in supplier relationships",
        "A.5.21": "Managing information security in the ICT supply chain",
        "A.5.23": "Information security for use of cloud services",
        "A.5.24": "Information security incident management planning",
        "A.5.26": "Response to information security incidents",
        "A.5.34": "Privacy and protection of PII",
        "A.8.7": "Protection against malware",
        "A.8.12": "Data leakage prevention",
        "A.8.16": "Monitoring activities",
    },
    "ISO42001": {
        "Human oversight": "Human oversight",
        "Outcome monitoring": "Outcome monitoring",
        "Risk treatment": "Risk treatment",
        "Model governance": "Model governance",
        "Prompt handling": "Prompt handling",
    },
    "EU AI Act": {
        "Article 9": "Risk Management System",
        "Article 14": "Human Oversight",
        "Article 15": "Accuracy, Robustness and Cybersecurity",
    },
    "PCI DSS": {
        "Req 6": "Develop and Maintain Secure Systems and Software",
        "Req 10": "Log and Monitor All Access to System Components",
        "Req 12": "Support Information Security with Organisational Policies",
    },
    "GDPR": {
        "Article 5": "Principles of Processing",
        "Article 32": "Security of Processing",
        "Article 33": "Breach Notification",
    },
    "PASTA": {
        "DefineObjectives": "Define Objectives",
        "DefineTechnicalScope": "Define Technical Scope",
        "ApplicationDecomposition": "Application Decomposition",
        "ThreatAnalysis": "Threat Analysis",
        "VulnerabilityAnalysis": "Vulnerability & Weakness Analysis",
        "ModellingAndSimulation": "Modelling and Simulation",
        "RiskAndImpactAnalysis": "Risk and Impact Analysis",
    },
}

_SIGNAL_TO_ATLAS: Dict[str, str] = {
    "prompt_injection": "AML.T0051",
    "ocr_prompt_injection": "AML.T0051",
    "qr_prompt_injection": "AML.T0051",
    "encoded_payload_detected": "AML.T0051",
    "homoglyph_injection": "AML.T0051",
    "exif_text_injection": "AML.T0051",
    "qr_external_url_detected": "AML.T0048",
    "qr_external_url": "AML.T0048",
    "qr_payload_vcard": "AML.T0048",
    "qr_payload_wifi": "AML.T0048",
    "qr_multi_mismatch": "AML.T0048",
    "qr_label_destination_mismatch": "AML.T0048",
    "polyglot_suspected": "AML.T0048",
    "cross_image_split_injection": "AML.T0051",
    "agentic_tool_injection": "AML.T0051",
    "agentic_tool_abuse": "AML.T0040",
}
_GENUINE_ATLAS_SIGNALS = frozenset(
    {
        "prompt_injection",
        "ocr_prompt_injection",
        "qr_prompt_injection",
        "encoded_payload_detected",
        "homoglyph_injection",
        "exif_text_injection",
        "cross_image_split_injection",
        "agentic_tool_injection",
        "agentic_tool_abuse",
    }
)

_SIGNAL_TO_ATTACK: Dict[str, str] = {
    "pci_card_exposed": "T1005",
    "ransomware_indicator": "T1486",
    "steg_suspicious": "T1027",
    "steg_score_elevated": "T1027",
}

_EXECUTION_HYPOTHESES = frozenset({"lolbin_command_sequence", "c2_beacon_pattern", "fileless_attack", "ransomware", "macro_auto_execution_lure"})
_OCR_ONLY_REF_PREFIXES = ("ocr.", "image.ocr", "image_ocr", "ocr_text", "qr.ocr")
_HIGHER_QUALITY_SIGNAL_QUALITIES = frozenset({"structural_parse", "runtime_confirmed", "analyst_verified"})


def _sha256_file(path: str) -> Optional[str]:
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return None
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _load_json(path: str) -> Dict[str, Any]:
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return {}
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _collect_cves_from_sbom(sbom: Dict[str, Any]) -> List[str]:
    cves: set[str] = set()
    vulns = sbom.get("vulnerabilities")
    if isinstance(vulns, list):
        for v in vulns:
            if not isinstance(v, dict):
                continue
            vid = str(v.get("id") or "").upper().strip()
            if vid.startswith("CVE-"):
                cves.add(vid)
    comps = sbom.get("components")
    if isinstance(comps, list):
        for c in comps:
            if not isinstance(c, dict):
                continue
            vv = c.get("vulnerabilities")
            if isinstance(vv, list):
                for item in vv:
                    if not isinstance(item, dict):
                        continue
                    vid = str(item.get("id") or "").upper().strip()
                    if vid.startswith("CVE-"):
                        cves.add(vid)
    return sorted(cves)


def _split_mitre(techniques: List[str] | None) -> Tuple[List[str], List[str]]:
    atlas: List[str] = []
    attack: List[str] = []
    for t in (techniques or []):
        s = str(t or "").strip()
        if not s:
            continue
        if s.upper().startswith("AML."):
            atlas.append(s)
        elif s.upper().startswith("T"):
            attack.append(s)
        else:
            attack.append(s)
    # stable dedupe
    def _uniq(items: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for x in items:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return _uniq(atlas), _uniq(attack)


def _validate_kill_chain_stage(stage: str | None) -> str:
    s = str(stage or "").strip()
    return s if s in _VALID_KILL_CHAIN_STAGES else ""


def _validate_pasta_stage(stage: str | None) -> str:
    s = str(stage or "").strip()
    if not s:
        return ""
    if ":" in s:
        sid, name = s.split(":", 1)
        if sid.startswith("Stage") and name in _VALID_PASTA_STAGE_NAMES:
            return f"{sid}:{name}"
        return ""
    return s if s in _VALID_PASTA_STAGE_NAMES else ""


def _canonical_control_name(framework: str, control: str) -> str:
    return (_CONTROL_NAME_CATALOG.get(str(framework), {}) or {}).get(str(control), "")


def _evidence_lines(evidence: Dict[str, Any] | None) -> List[str]:
    out: List[str] = []
    ev = evidence or {}
    for row in list((ev.get("top_ranked_findings") or [])[:4]):
        if isinstance(row, dict):
            summary = str(row.get("summary") or row.get("business_meaning") or "").strip()
            if summary:
                out.append(summary)
            for item in (row.get("evidence") or [])[:2]:
                s = str(item or "").strip()
                if s:
                    out.append(s)
    for item in (ev.get("artifact_evidence") or [])[:6]:
        s = str(item or "").strip()
        if s:
            out.append(s)
    for item in (ev.get("artifact_claims") or [])[:8]:
        if not isinstance(item, dict):
            continue
        if str(item.get("claim_status") or "").strip().lower() == "suppressed":
            continue
        summary = str(item.get("summary") or "").strip()
        if summary:
            out.append(summary)
        for line in (item.get("evidence_summary") or [])[:2]:
            s = str(line or "").strip()
            if s:
                out.append(s)
    seen = set()
    return [x for x in out if x and not (x in seen or seen.add(x))]


def _case_evidence_refs(signals: Dict[str, Any], evidence: Dict[str, Any] | None) -> List[str]:
    ev = evidence or {}
    refs: List[str] = []
    if bool(signals.get("dmarc_fail")):
        refs.append("sender.auth_alignment_failed")
    if bool(signals.get("semantic_bec_high_risk")):
        refs.append("semantic_bec.high_risk")
    if bool(signals.get("thread_sender_domain_drift")):
        refs.append("thread.sender_domain_drift")
    if bool(signals.get("thread_reentry_after_silence")):
        refs.append("thread.reentry_after_silence")
    if bool(signals.get("yara_match")):
        refs.append("yara.match")
    if bool(signals.get("yara_high_confidence")):
        refs.append("yara.high_confidence_match")
    if ((ev.get("sender_infrastructure") or {}).get("related_incident_count") or 0):
        refs.append("infra.related_incidents")
    if (ev.get("trust_case") or {}).get("approved_contact_path_missing"):
        refs.append("workflow.no_approved_callback_match")
    if (ev.get("case_facts") or {}).get("from_addr"):
        refs.append("sender.claimed_identity")
    if (ev.get("case_facts") or {}).get("reply_to"):
        refs.append("sender.reply_to")
    for item in (ev.get("artifact_claims") or [])[:8]:
        if not isinstance(item, dict):
            continue
        if str(item.get("claim_status") or "").strip().lower() == "suppressed":
            continue
        for ref in (item.get("evidence_refs") or [])[:6]:
            s = str(ref or "").strip()
            if s:
                refs.append(s)
    for idx, _ in enumerate((ev.get("top_ranked_findings") or [])[:3], start=1):
        refs.append(f"finding.top_ranked.{idx}")
    seen = set()
    return [x for x in refs if x and not (x in seen or seen.add(x))]


def _artifact_claims(evidence: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in ((evidence or {}).get("artifact_claims") or [])[:24]:
        if not isinstance(item, dict):
            continue
        if str(item.get("claim_status") or "").strip().lower() == "suppressed":
            continue
        out.append(item)
    return out


def _claim_refs_and_summary(claims: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    refs: List[str] = []
    summary: List[str] = []
    for item in claims:
        for ref in (item.get("evidence_refs") or [])[:6]:
            s = str(ref or "").strip()
            if s:
                refs.append(s)
        for line in (item.get("evidence_summary") or [])[:3]:
            s = str(line or "").strip()
            if s:
                summary.append(s)
        claim_summary = str(item.get("summary") or "").strip()
        if claim_summary:
            summary.append(claim_summary)
    seen_refs = set()
    seen_summary = set()
    return (
        [x for x in refs if x and not (x in seen_refs or seen_refs.add(x))],
        [x for x in summary if x and not (x in seen_summary or seen_summary.add(x))],
    )


def _claim_primary_artifact_type(claim: Dict[str, Any] | None) -> str:
    source_type = str((claim or {}).get("source_type") or "").strip().lower()
    mapping = {
        "ocr": "attachment text extraction",
        "cv": "uploaded image analysis",
        "attachment": "email attachment",
        "behavioral": "static behavioral signature",
        "sandbox": "runtime sandbox telemetry",
        "model": "model-facing content",
        "agentic": "agentic workflow input",
    }
    return mapping.get(source_type, source_type.replace("_", " ") if source_type else "security artifact")


def _refs_are_ocr_only(refs: List[str]) -> bool:
    clean = [str(ref or "").strip().lower() for ref in refs if str(ref or "").strip()]
    return bool(clean) and all(any(ref.startswith(prefix) for prefix in _OCR_ONLY_REF_PREFIXES) for ref in clean)


def _ocr_confidence_from_evidence(evidence: Dict[str, Any] | None) -> float | None:
    ev = evidence or {}
    for key in ("ocr_confidence",):
        try:
            if ev.get(key) is not None:
                return float(ev.get(key))
        except Exception:
            pass
    for item in _artifact_claims(ev):
        try:
            if item.get("ocr_confidence") is not None:
                return float(item.get("ocr_confidence"))
        except Exception:
            continue
    return None


def _dread_evidence_quality(dread: Dict[str, Any] | None) -> Dict[str, Any]:
    items = list((dread or {}).get("evidence") or [])
    qualities = [
        str((item or {}).get("signal_quality") or "").strip().lower()
        for item in items
        if str((item or {}).get("signal_quality") or "").strip()
    ]
    if not qualities:
        return {
            "band": "LOW",
            "label": "Heuristic only — evidence quality metadata unavailable",
            "numeric_withheld": True,
            "max_quality": "heuristic",
            "all_heuristic": True,
            "score_cap": 6.0,
        }
    if any(q == "runtime_confirmed" for q in qualities):
        return {
            "band": "HIGH",
            "label": "Runtime-confirmed evidence present",
            "numeric_withheld": False,
            "max_quality": "runtime_confirmed",
            "all_heuristic": False,
            "score_cap": None,
        }
    if any(q in _HIGHER_QUALITY_SIGNAL_QUALITIES for q in qualities):
        return {
            "band": "MEDIUM",
            "label": "Structural or analyst-verified evidence present",
            "numeric_withheld": False,
            "max_quality": "structural_parse",
            "all_heuristic": False,
            "score_cap": None,
        }
    return {
        "band": "LOW",
        "label": "Heuristic only — keyword or severity-driven evidence",
        "numeric_withheld": True,
        "max_quality": "keyword_match",
        "all_heuristic": True,
        "score_cap": 6.0,
    }


def _claims_for_control(
    evidence: Dict[str, Any] | None,
    *,
    framework: str,
    control: str,
    include_possible: bool = True,
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for item in _artifact_claims(evidence):
        keys: List[str] = []
        if framework == "MITRE ATT&CK":
            keys = [str(x) for x in (item.get("mitre_attack") or [])]
            if include_possible:
                keys.extend(str(x) for x in (item.get("possible_mitre_attack") or []))
        elif framework == "MITRE ATLAS":
            keys = [str(x) for x in (item.get("mitre_atlas") or [])]
            if include_possible:
                keys.extend(str(x) for x in (item.get("possible_mitre_atlas") or []))
        elif framework == "PASTA":
            keys = [_validate_pasta_stage(item.get("pasta_stage"))]
        if control in keys:
            matched.append(item)
    return matched


def _business_significance_from_claims(
    framework: str,
    control: str,
    claims: List[Dict[str, Any]],
    evidence_lines: List[str],
    evidence: Dict[str, Any] | None = None,
) -> str:
    case_route = str((((evidence or {}).get("case_facts") or {}).get("route") or "review")).strip().lower() or "review"
    for item in claims:
        outcome = str(item.get("business_outcome") or "").strip()
        claim_status = str(item.get("claim_status") or "inferred").strip().lower() or "inferred"
        artifact_type = _claim_primary_artifact_type(item)
        finding = str(item.get("finding_type") or item.get("summary") or control).strip().replace("_", " ")
        if outcome:
            return (
                f"{_canonical_control_name(framework, control) or control} is relevant because {finding} was {claim_status} "
                f"from a {artifact_type}. Current route is {case_route}. {outcome}"
            )
    return _business_significance(framework, control, evidence_lines, evidence=evidence)


def _has_genuine_atlas_evidence(signals: Dict[str, Any], evidence: Dict[str, Any] | None) -> bool:
    sigs = signals or {}
    if any(bool(sigs.get(key)) for key in _GENUINE_ATLAS_SIGNALS):
        return True
    for item in ((evidence or {}).get("artifact_claims") or [])[:12]:
        if not isinstance(item, dict):
            continue
        if str(item.get("claim_status") or "").strip().lower() == "suppressed":
            continue
        if item.get("model_targeting_evidence"):
            return True
        finding_type = str(item.get("finding_type") or "").strip().lower()
        if finding_type in {"prompt_injection_hidden", "agentic_tool_instruction", "cross_modal_prompt_injection"}:
            return True
        if str(item.get("source_type") or "").strip().lower() in {"model", "agentic"}:
            return True
    return False


def _business_significance(framework: str, control: str, evidence_lines: List[str], evidence: Dict[str, Any] | None = None) -> str:
    fw = str(framework)
    ctl = str(control)
    case_facts = (evidence or {}).get("case_facts") or {}
    route = str(case_facts.get("route") or "review").strip().lower() or "review"
    artifact_type = "email attachment" if any("xlsm" in str(line).lower() or "pdf" in str(line).lower() for line in evidence_lines) else "security artifact"
    if fw == "ISO27001" and ctl == "A.5.19":
        return f"Information security in supplier relationships is relevant because {artifact_type} evidence indicates a supplier-verification break. Current route is {route}. This can enable an unauthorized beneficiary or payment path change."
    if fw == "ISO27001" and ctl == "A.8.7":
        return f"Protection against malware is relevant because a macro-enabled or suspicious {artifact_type} was detected. Current route is {route}. The file requires malware scanning, detonation, and endpoint protection controls before any user action."
    if fw == "ISO27001" and ctl == "A.8.16":
        return f"Monitoring activities matter here because the current route is {route} and auditability must preserve how the artifact was triaged, escalated, and contained."
    if fw == "PCI DSS" and ctl == "Req 10":
        return f"PCI DSS logging is relevant because the current route is {route}. Weak logging would make payment-hold, escalation, and analyst actions difficult to reconstruct or defend."
    if fw == "EU AI Act" and ctl == "Article 14":
        return f"EU AI Act human oversight is relevant because AI-assisted security analysis influenced a {route} decision. Human review is required before consequential action."
    if fw == "EU AI Act" and ctl == "Article 15":
        return f"Accuracy, robustness, and cybersecurity are relevant because the current route is {route} and AI-assisted output must not overstate weak evidence."
    if fw == "GDPR" and ctl == "Article 32":
        return f"Security of processing is relevant because the current route is {route} and confirmed sensitive-data handling would require appropriate technical and organizational controls."
    if fw == "MITRE ATT&CK" and ctl == "T1566.001":
        return f"Spearphishing attachment is relevant because a deceptive {artifact_type} increased the likelihood of user action on fraudulent instructions. Current route is {route}."
    if fw == "MITRE ATT&CK" and ctl == "T1059.001":
        return f"PowerShell remains a runtime-confirmation path only. If execution is later confirmed from the current {artifact_type}, the endpoint could execute follow-on commands."
    if fw == "MITRE ATT&CK" and ctl == "T1105":
        return f"Ingress tool transfer remains a runtime-confirmation path only. If confirmed from this {artifact_type}, the chain could fetch a second-stage payload from attacker-controlled infrastructure."
    if fw == "MITRE ATT&CK" and ctl == "T1140":
        return f"Deobfuscate/decode remains a runtime-confirmation path only. If certutil or similar unpacking is confirmed from this {artifact_type}, staged payload content could be unwrapped for execution."
    if fw == "MITRE ATT&CK" and ctl in {"T1218.005", "T1218.010", "T1218.011"}:
        return f"Signed-binary proxy execution remains unconfirmed. If confirmed from this {artifact_type}, a trusted Windows binary could proxy malicious execution while blending into normal endpoint activity."
    if fw == "MITRE ATT&CK" and ctl == "T1059.005":
        return f"Visual Basic/script-host execution remains unconfirmed. If runtime evidence later confirms it, the current {artifact_type} could trigger code through Windows Script Host or Office scripting."
    if fw == "MITRE ATLAS" and ctl == "AML.T0043":
        return f"Craft adversarial data is only relevant if model-targeting evidence is present. Without that, this remains a speculative AI-security mapping for the current {artifact_type}."
    if fw == "PASTA":
        return f"This stage indicates where the current {artifact_type} sits in the modeled attack path and how urgently controls should respond."
    return (
        f"{_canonical_control_name(framework, control) or control} is relevant because the current {artifact_type} produced evidence that routed the case to {route}. "
        f"{evidence_lines[0] if evidence_lines else 'Independent verification is still required.'}"
    )


def _build_framework_row(
    *,
    framework: str,
    control: str,
    trigger_reason: str,
    evidence_refs: List[str],
    evidence_summary: List[str],
    mapping_confidence: str,
    why_triggered: str,
    business_significance: str,
    mapping_source: str,
    control_implemented: Any = None,
    evidence_of_control: Any = None,
    case_driver: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "framework": framework,
        "control_or_tag": control,
        "canonical_name": _canonical_control_name(framework, control) or control,
        "trigger_reason": trigger_reason,
        "evidence_refs": list(evidence_refs),
        "evidence_summary": list(evidence_summary),
        "why_triggered": why_triggered,
        "business_significance": business_significance,
        "mapping_source": mapping_source,
        "mapping_version": _FRAMEWORK_MAPPING_VERSION,
        "mapping_confidence": mapping_confidence,
        "analyst_review_required": True,
        "rule_id": f"{framework.lower().replace(' ', '_')}::{str(control).lower().replace(' ', '_')}",
        "control_implemented": control_implemented,
        "evidence_of_control": evidence_of_control,
        "case_driver": case_driver or {},
    }


def _build_framework_rows(
    *,
    signals: Dict[str, Any],
    mitre_attack: List[str],
    mitre_atlas: List[str],
    pasta_stage: str,
    compliance: Dict[str, Any],
    evidence: Dict[str, Any] | None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    evidence_refs = _case_evidence_refs(signals, evidence)
    evidence_summary = _evidence_lines(evidence)
    claim_rows = _artifact_claims(evidence)
    ocr_confidence = _ocr_confidence_from_evidence(evidence)
    rows: List[Dict[str, Any]] = []
    possible_rows: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []

    def _append(row: Dict[str, Any], *, possible: bool = False) -> None:
        refs = list(row.get("evidence_refs") or [])
        if refs:
            if ocr_confidence is not None and ocr_confidence < 0.65 and _refs_are_ocr_only(refs):
                row["mapping_confidence"] = "low"
                row["why_triggered"] = f"{row.get('why_triggered') or ''} [DEGRADED: sole evidence source is low-confidence OCR ({ocr_confidence:.2f})]".strip()
                possible_rows.append(row)
            elif possible:
                possible_rows.append(row)
            else:
                rows.append(row)
        else:
            suppressed.append({**row, "suppressed_reason": "missing_evidence_refs"})

    pasta_valid = _validate_pasta_stage(pasta_stage)
    if pasta_valid:
        pasta_claims = [item for item in claim_rows if _validate_pasta_stage(item.get("pasta_stage")) == pasta_valid]
        pasta_refs, pasta_summary = _claim_refs_and_summary(pasta_claims)
        _, stage_name = pasta_valid.split(":", 1)
        _append(
            _build_framework_row(
                framework="PASTA",
                control=stage_name,
                trigger_reason="validated_pasta_stage",
                evidence_refs=(pasta_refs or evidence_refs)[:6],
                evidence_summary=(pasta_summary or evidence_summary)[:4],
                mapping_confidence="high" if (pasta_refs or evidence_refs) else "low",
                why_triggered="Validated PASTA stage from backend threat-model correlation and structured attachment findings. Kill-chain values are not used as a fallback.",
                business_significance=_business_significance_from_claims("PASTA", stage_name, pasta_claims, pasta_summary or evidence_summary, evidence),
                mapping_source="framework_correlation._pasta_claims",
                case_driver={
                    "artifact_property": (pasta_refs or evidence_refs or [""])[0],
                    "extraction_method": str((pasta_claims[0] if pasta_claims else {}).get("source_type") or "structured_correlation"),
                    "matched_pattern": (pasta_summary or evidence_summary or [""])[0],
                    "offset_or_location": (pasta_refs or evidence_refs or [""])[0],
                },
            )
        )
    elif pasta_stage:
        suppressed.append(
            {
                "framework": "PASTA",
                "control_or_tag": pasta_stage,
                "suppressed_reason": "invalid_pasta_stage",
                "mapping_source": "framework_correlation._pasta",
                "mapping_version": _FRAMEWORK_MAPPING_VERSION,
            }
        )

    for control in mitre_attack:
        strong_attack_claims = [
            item
            for item in _claims_for_control(evidence, framework="MITRE ATT&CK", control=control, include_possible=False)
            if str(item.get("claim_status") or "").strip().lower() in {"observed", "inferred"}
        ]
        possible_attack_claims = [
            item
            for item in _claims_for_control(evidence, framework="MITRE ATT&CK", control=control, include_possible=True)
            if str(item.get("claim_status") or "").strip().lower() == "possible"
        ]
        attack_claims = strong_attack_claims or possible_attack_claims
        attack_refs, attack_summary = _claim_refs_and_summary(attack_claims)
        confidence = "high" if strong_attack_claims else ("medium" if possible_attack_claims else ("low" if evidence_refs else "low"))
        _append(
            _build_framework_row(
                framework="MITRE ATT&CK",
                control=control,
                trigger_reason="artifact_claim_match" if attack_claims else "threat_signal_match",
                evidence_refs=(attack_refs or evidence_refs)[:6],
                evidence_summary=(attack_summary or evidence_summary)[:4],
                mapping_confidence=confidence,
                why_triggered=(
                    "Structured attachment findings matched this ATT&CK technique and carried case-specific evidence references."
                    if strong_attack_claims
                    else "Passive attachment evidence suggested this ATT&CK technique, but runtime confirmation is still required before treating it as confirmed."
                    if possible_attack_claims
                    else "Catalog-driven ATT&CK mapping exists for this signal family, but no case-backed observed claim has been recorded yet."
                ),
                business_significance=_business_significance_from_claims("MITRE ATT&CK", control, attack_claims, attack_summary or evidence_summary, evidence),
                mapping_source="framework_correlation.artifact_claims" if attack_claims else "framework_correlation.mitre_attack",
                case_driver={
                    "artifact_property": (attack_refs or evidence_refs or [""])[0],
                    "extraction_method": str((attack_claims[0] if attack_claims else {}).get("source_type") or "signal_bundle"),
                    "matched_pattern": (attack_summary or evidence_summary or [""])[0],
                    "offset_or_location": (attack_refs or evidence_refs or [""])[0],
                },
            ),
            possible=not bool(strong_attack_claims),
        )
    for control in mitre_atlas:
        strong_atlas_claims = [
            item
            for item in _claims_for_control(evidence, framework="MITRE ATLAS", control=control, include_possible=False)
            if str(item.get("claim_status") or "").strip().lower() in {"observed", "inferred"}
        ]
        possible_atlas_claims = [
            item
            for item in _claims_for_control(evidence, framework="MITRE ATLAS", control=control, include_possible=True)
            if str(item.get("claim_status") or "").strip().lower() == "possible"
        ]
        atlas_claims = strong_atlas_claims or possible_atlas_claims
        atlas_refs, atlas_summary = _claim_refs_and_summary(atlas_claims)
        row = _build_framework_row(
            framework="MITRE ATLAS",
            control=control,
            trigger_reason="artifact_claim_match" if atlas_claims else "adversarial_ai_signal_match",
            evidence_refs=(atlas_refs or evidence_refs)[:6],
            evidence_summary=(atlas_summary or evidence_summary)[:4],
            mapping_confidence="high" if strong_atlas_claims else ("medium" if possible_atlas_claims else ("medium" if (atlas_refs or evidence_refs) else "low")),
            why_triggered="Structured claims contained genuine model-targeting evidence that matched an ATLAS technique." if strong_atlas_claims else "Potential model-targeting indicators were observed, but the evidence remains hypothesis-grade until confirmed." if possible_atlas_claims else "Observed content or workflow signals matched an ATLAS technique associated with adversarial AI or ML misuse.",
            business_significance=_business_significance_from_claims("MITRE ATLAS", control, atlas_claims, atlas_summary or evidence_summary, evidence),
            mapping_source="framework_correlation.artifact_claims" if atlas_claims else "framework_correlation.mitre_atlas",
            case_driver={
                "artifact_property": (atlas_refs or evidence_refs or [""])[0],
                "extraction_method": str((atlas_claims[0] if atlas_claims else {}).get("source_type") or "signal_bundle"),
                "matched_pattern": (atlas_summary or evidence_summary or [""])[0],
                "offset_or_location": (atlas_refs or evidence_refs or [""])[0],
            },
        )
        if _has_genuine_atlas_evidence(signals, evidence):
            _append(row, possible=not bool(strong_atlas_claims))
        else:
            suppressed.append({**row, "suppressed_reason": "no_genuine_model_targeting_evidence"})
    for item in (compliance.get("frameworks") or []):
        if not isinstance(item, dict):
            continue
        framework = str(item.get("framework") or "").strip()
        for control in (item.get("controls") or []):
            registry_row = get_control_record(framework, str(control))
            registry_version = get_control_registry_version()
            control_impl = item.get("control_implemented", registry_row.get("control_implemented"))
            evidence_of_control = item.get("evidence_of_control", registry_row.get("evidence_of_control"))
            control_desc = str(item.get("control_description") or registry_row.get("control_description") or "").strip()
            compliance_possible = any(
                str(item.get("claim_status") or "").strip().lower() == "possible"
                for item in claim_rows
            ) and not any(
                str(item.get("claim_status") or "").strip().lower() in {"observed", "inferred"}
                for item in claim_rows
            )
            row = _build_framework_row(
                framework=framework,
                control=str(control),
                trigger_reason="compliance_policy_match",
                evidence_refs=evidence_refs[:4],
                evidence_summary=evidence_summary[:3],
                mapping_confidence="medium" if evidence_refs else "low",
                why_triggered=(
                    "Compliance mapping was generated from validated case signals and only renders when evidence references are available."
                    + (f" Control evidence: {control_desc}" if control_desc else "")
                ),
                business_significance=_business_significance(framework, str(control), evidence_summary, evidence=evidence),
                mapping_source=(
                    f"framework_correlation._compliance + control_registry@{registry_version}"
                    if registry_row
                    else "framework_correlation._compliance"
                ),
                control_implemented=control_impl,
                evidence_of_control=evidence_of_control,
                case_driver={
                    "artifact_property": (evidence_refs or [""])[0],
                    "extraction_method": "case_signal_bundle",
                    "matched_pattern": (evidence_summary or [""])[0],
                    "offset_or_location": (evidence_refs or [""])[0],
                },
            )
            if framework in {"ISO42001", "EU AI Act", "GDPR"} and (control_impl in (None, "", "untested") or not evidence_of_control):
                possible_rows.append({**row, "mapping_confidence": "low", "why_triggered": f"{row['why_triggered']} Control evidence is missing or untested, so this row stays possible."})
            elif framework in {"ISO42001", "EU AI Act", "GDPR"} and str(control_impl).strip().lower() != "true":
                possible_rows.append({**row, "mapping_confidence": "medium", "why_triggered": f"{row['why_triggered']} Control evidence exists but implementation status is {control_impl}; keep as possible until fully audited."})
            else:
                _append(row, possible=compliance_possible)
    return rows, possible_rows, suppressed


def _build_dread_dimensions(dread: Dict[str, Any] | None, evidence: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    dd = dread or {}
    case_refs = _case_evidence_refs({}, evidence)
    case_summary = _evidence_lines(evidence)
    quality = _dread_evidence_quality(dread)
    ocr_confidence = _ocr_confidence_from_evidence(evidence)
    out: Dict[str, Dict[str, Any]] = {}
    for key in ("damage", "reproducibility", "exploitability", "affected_users", "discoverability"):
        value = dd.get(key)
        component_items = [
            item
            for item in (dd.get("evidence") or [])
            if str((item or {}).get("component") or "").strip() == key
        ]
        drivers = [
            str((item or {}).get("signal") or "").strip()
            for item in component_items
            if str((item or {}).get("signal") or "").strip()
        ]
        qualities = [
            str((item or {}).get("signal_quality") or "").strip().lower()
            for item in component_items
            if str((item or {}).get("signal_quality") or "").strip()
        ]
        display_score = value
        band_value = float(value or 0)
        withheld_reason = ""
        if quality.get("numeric_withheld"):
            display_score = None
            band_value = min(band_value, float(quality.get("score_cap") or 6.0))
            withheld_reason = "Numeric DREAD scores withheld because the supporting evidence is heuristic only."
        if ocr_confidence is not None and ocr_confidence < 0.65 and _refs_are_ocr_only(case_refs):
            display_score = None
            band_value = min(band_value, 5.0)
            withheld_reason = f"OCR confidence below threshold ({ocr_confidence:.2f}); numeric DREAD scores are withheld pending independent verification."
        evidence_refs = case_refs[:4] if drivers else case_refs[:2]
        out[key] = {
            "score": display_score if drivers else None,
            "band": ("high" if band_value >= 8 else "moderate" if band_value >= 5 else "low") if value is not None else "unknown",
            "drivers": drivers,
            "evidence_refs": evidence_refs,
            "evidence_summary": case_summary[:2],
            "why_it_matters": _business_significance("DREAD", key, case_summary, evidence=evidence),
            "signal_quality": max(qualities) if qualities else quality.get("max_quality"),
            "numeric_withheld": bool(withheld_reason),
            "numeric_withheld_reason": withheld_reason or None,
        }
    return out


def _stride_from_signals(signals: Dict[str, Any], tags: List[str]) -> List[str]:
    tset = {str(t or "").lower() for t in (tags or [])}
    s = signals or {}
    out: List[str] = []

    # Spoofing: impersonation, lookalikes, auth alignment failure.
    if any(k in tset for k in ("bec", "brand_impersonation", "lookalike_domain", "reply_to_mismatch")):
        out.append("Spoofing")
    if bool(s.get("dmarc_fail")) or bool(s.get("auth_alignment_failed")):
        out.append("Spoofing")
    if bool(s.get("homoglyph")) or bool(s.get("unicode_confusable")) or bool(s.get("homoglyph_injection")):
        out.append("Spoofing")

    # Tampering: document/image manipulation, layout/text divergence.
    if (
        bool(s.get("manipulation_detected"))
        or bool(s.get("layout_text_divergence"))
        or bool(s.get("cross_modal_mismatch"))
        or bool(s.get("ocr_yolo_label_conflict"))
        or bool(s.get("vision_yolo_conflict"))
    ):
        out.append("Tampering")
    if bool(s.get("qr_code_detected")) or bool(s.get("qr_external_url_detected")) or bool(s.get("qr_external_url")):
        out.append("Tampering")

    # Repudiation: covert channels / missing audit linkage.
    if bool(s.get("email_c2_beaconing")) or bool(s.get("thread_hijack")):
        out.append("Repudiation")

    # Information disclosure: exfil / secrets / PII.
    if (
        bool(s.get("data_exfiltration"))
        or bool(s.get("pii"))
        or bool(s.get("api_key"))
        or bool(s.get("pci_card_exposed"))
    ):
        out.append("InformationDisclosure")

    # Denial of service: burst, lock contention, rate anomalies.
    if bool(s.get("scanner_burst")) or bool(s.get("rate_anomaly")):
        out.append("DenialOfService")

    # Elevation of privilege: tool abuse / bypass attempts.
    if (
        bool(s.get("agentic_tool_abuse"))
        or bool(s.get("agentic_tool_injection"))
        or bool(s.get("cross_image_split_injection"))
        or bool(s.get("prompt_injection"))
        or bool(s.get("dangerous_tool_intent"))
        or bool(s.get("qr_prompt_injection"))
        or bool(s.get("ocr_prompt_injection"))
    ):
        out.append("ElevationOfPrivilege")

    # stable dedupe
    seen = set()
    return [x for x in out if x and (x not in seen and not seen.add(x))]


def _pasta(signals: Dict[str, Any], severity: str | None, *, dread: Dict[str, Any] | None = None) -> Dict[str, Any]:
    # Mirror the observer's staging logic for consistent trace drilldowns.
    stages = [
        {"id": "Stage1", "name": "DefineObjectives"},
        {"id": "Stage2", "name": "DefineTechnicalScope"},
        {"id": "Stage3", "name": "ApplicationDecomposition"},
        {"id": "Stage4", "name": "ThreatAnalysis"},
        {"id": "Stage5", "name": "VulnerabilityAnalysis"},
        {"id": "Stage6", "name": "ModellingAndSimulation"},
        {"id": "Stage7", "name": "RiskAndImpactAnalysis"},
    ]
    current = "Stage1"
    stage_rank = {item["id"]: idx + 1 for idx, item in enumerate(stages)}
    try:
        claim_stages: List[Tuple[int, str]] = []
        for item in _artifact_claims((dread or {}).get("evidence_context")):
            validated = _validate_pasta_stage(item.get("pasta_stage"))
            if not validated or ":" not in validated:
                continue
            stage_id, _ = validated.split(":", 1)
            if stage_id not in stage_rank:
                continue
            status = str(item.get("claim_status") or "").strip().lower()
            weight = 200 if status in {"observed", "inferred"} else 100 if status == "possible" else 0
            claim_stages.append((weight + stage_rank[stage_id], stage_id))
        if claim_stages:
            current = sorted(claim_stages, key=lambda x: x[0], reverse=True)[0][1]

        active_count = sum(1 for v in (signals or {}).values() if bool(v))
        if active_count >= 1 and stage_rank[current] < 3:
            current = "Stage3"
        if active_count >= 2 and stage_rank[current] < 4:
            current = "Stage4"
        if active_count >= 3 and stage_rank[current] < 5:
            current = "Stage5"
        if bool(signals.get("supply_chain")) or bool(signals.get("training_poisoning")):
            current = "Stage3"
        if bool(signals.get("jailbreak")) or bool(signals.get("prompt_injection")) or bool(signals.get("agentic_tool_abuse")):
            current = "Stage4"
        if bool(signals.get("cross_image_split_injection")) or bool(signals.get("agentic_tool_injection")):
            current = "Stage4"
        if bool(signals.get("data_exfiltration")) or bool(signals.get("pci")) or bool(signals.get("pii")) or bool(signals.get("pci_card_exposed")):
            current = "Stage5"
        if bool(signals.get("cross_modal_mismatch")) or bool(signals.get("multimodal_attack_surface_high")):
            current = "Stage5"
        if bool(signals.get("steg_suspicious")) or bool(signals.get("steg_score_elevated")):
            current = "Stage4"
        late_claim_stage = ""
        for item in _artifact_claims((dread or {}).get("evidence_context")):
            validated = _validate_pasta_stage(item.get("pasta_stage"))
            if not validated or ":" not in validated:
                continue
            if (
                str(item.get("finding_type") or "").strip().lower() in _EXECUTION_HYPOTHESES
                and bool(item.get("runtime_confirmation_required"))
                and not (item.get("runtime_evidence_present") or [])
            ):
                continue
            stage_id, _ = validated.split(":", 1)
            if stage_id in {"Stage6", "Stage7"} and str(item.get("claim_status") or "").strip().lower() in {"observed", "inferred"}:
                late_claim_stage = stage_id
                break
        if late_claim_stage and stage_rank[current] < stage_rank[late_claim_stage]:
            current = late_claim_stage
    except Exception:
        pass
    workflow: List[Dict[str, Any]] = []
    reached = False
    for s in stages:
        if s["id"] == current:
            workflow.append({**s, "status": "current"})
            reached = True
        elif not reached:
            workflow.append({**s, "status": "complete"})
        else:
            workflow.append({**s, "status": "pending"})
    name = next((x["name"] for x in stages if x["id"] == current), "DefineObjectives")
    return {"current_stage": current, "pasta_stage": f"{current}:{name}", "stages": workflow}


def _lev(dread: Dict[str, Any] | None, cvss: Dict[str, Any] | None) -> Dict[str, Any]:
    # Lightweight "LEV" proxy for demo: Likelihood, Exposure, Value (0..1).
    # Derived deterministically from DREAD/CVSS to make cross-framework drilldown consistent.
    try:
        dread_avg = float((dread or {}).get("avg") or 0.0) / 10.0
    except Exception:
        dread_avg = 0.0
    try:
        cvss_score = float((cvss or {}).get("score") or 0.0) / 10.0
    except Exception:
        cvss_score = 0.0
    likelihood = max(0.0, min(1.0, (dread_avg * 0.7) + (cvss_score * 0.3)))
    exposure = max(0.0, min(1.0, (cvss_score * 0.8) + (dread_avg * 0.2)))
    value = max(0.0, min(1.0, (dread_avg * 0.5) + (cvss_score * 0.5)))
    score = max(0.0, min(1.0, (likelihood + exposure + value) / 3.0))
    return {
        "likelihood": round(likelihood, 3),
        "exposure": round(exposure, 3),
        "value": round(value, 3),
        "score": round(score, 3),
    }


def _sbom_snapshot() -> Dict[str, Any]:
    sbom_path = os.getenv("SBOM_PATH") or ("sbom.json" if Path("sbom.json").exists() else None)
    kev_path = os.getenv("KEV_CATALOG_PATH", os.path.join("config", "security", "taxonomy", "kev_catalog.json"))
    sbom_obj = _load_json(sbom_path) if sbom_path else {}
    cves = _collect_cves_from_sbom(sbom_obj if isinstance(sbom_obj, dict) else {})
    kev = _load_json(kev_path)
    kev_hits = [c for c in cves if c in kev] if isinstance(kev, dict) else []
    risk_band = "low"
    if kev_hits:
        risk_band = "high"
    elif cves:
        risk_band = "medium"
    return {
        "slsa_level": (os.getenv("SLSA_LEVEL") or "").strip() or None,
        "sbom_path": sbom_path,
        "cve_count": len(cves),
        "cves": cves[:128],
        "kev_hits": kev_hits[:128],
        "risk_band": risk_band,
        "python_manifest": {"path": "pyproject.toml", "sha256": _sha256_file("pyproject.toml")},
        "node_manifest": {"path": "frontend/package-lock.json", "sha256": _sha256_file(os.path.join("frontend", "package-lock.json"))},
    }


def _compliance(signals: Dict[str, Any], tags: List[str]) -> Dict[str, Any]:
    # Defensive-only: map to a small set of common security program frameworks.
    # This is intended for evidence and routing, not certification claims.
    tset = {str(t or "").lower() for t in (tags or [])}
    s = signals or {}
    nist_csf: List[str] = []
    iso27001: List[str] = []
    soc2: List[str] = []

    # Detect/Respond are common to most security incidents.
    if any(bool(v) for v in s.values()) or tset:
        nist_csf.extend(["DE.CM", "RS.MI"])
        soc2.extend(["CC7.2", "CC7.3"])

    if bool(s.get("dmarc_fail")) or "dmarc" in tset or "bec" in tset:
        nist_csf.extend(["PR.AA", "DE.CM"])
        iso27001.extend(["A.5.16", "A.5.17"])  # Identity/access + auth info (approximate)
        soc2.extend(["CC6.1", "CC6.2"])

    if bool(s.get("prompt_injection")) or bool(s.get("agentic_tool_abuse")):
        nist_csf.extend(["PR.AA", "PR.DS", "DE.CM", "RS.MI"])
        iso27001.extend(["A.5.8", "A.8.7"])  # Information security in PM + malware protection (approximate)
        soc2.extend(["CC6.6", "CC7.2"])

    if bool(s.get("data_exfiltration")) or bool(s.get("pii")) or bool(s.get("api_key")):
        nist_csf.extend(["PR.DS", "DE.CM", "RS.MI"])
        iso27001.extend(["A.8.12", "A.5.34"])  # DLP + privacy/PII (approximate)
        soc2.extend(["CC6.7", "CC7.3"])

    if bool(s.get("supply_chain")):
        nist_csf.extend(["ID.SC", "PR.SR"])
        iso27001.extend(["A.5.19", "A.5.21"])  # Supplier relationships
        soc2.extend(["CC8.1"])

    # stable dedupe
    def _uniq(xs: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for x in xs:
            if x and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return {
        "frameworks": [
            {"framework": "NIST_CSF", "controls": _uniq(nist_csf)},
            {"framework": "ISO27001", "controls": _uniq(iso27001)},
            {"framework": "SOC2", "controls": _uniq(soc2)},
        ]
    }


def _d3fend_suggestions(signals: Dict[str, Any], tags: List[str]) -> List[Dict[str, Any]]:
    """Suggest defensive controls aligned with observed signals.

    This is an auto-suggestion helper for triage, not a hard policy decision.
    """
    s = signals or {}
    tset = {str(t or "").lower() for t in (tags or [])}
    out: List[Dict[str, Any]] = []

    def _add(control: str, rationale: str, priority: str = "medium") -> None:
        out.append(
            {
                "framework": "D3FEND",
                "control": control,
                "priority": priority,
                "rationale": rationale,
            }
        )

    if bool(s.get("prompt_injection")) or bool(s.get("jailbreak")) or bool(s.get("agentic_tool_abuse")):
        _add("Input Validation / Canonicalization", "Prompt or tool-abuse signal detected", priority="high")
        _add("Execution Policy Enforcement", "Reduce unauthorized tool invocation paths", priority="high")

    if bool(s.get("dmarc_fail")) or "dmarc" in tset or bool(s.get("auth_alignment_failed")):
        _add("Email Authentication Enforcement (DMARC/DKIM/SPF)", "Sender auth alignment risk present", priority="high")

    if bool(s.get("data_exfiltration")) or bool(s.get("pii")) or bool(s.get("api_key")):
        _add("Data Loss Prevention", "Sensitive data exposure indicators detected", priority="high")
        _add("Credential Exposure Monitoring", "Potential secret/API-key leakage signal", priority="high")

    if bool(s.get("supply_chain")) or bool(s.get("training_poisoning")):
        _add("Dependency Provenance & Integrity Verification", "Supply-chain/training-poisoning signals observed", priority="high")
        _add("SBOM-Based Vulnerability Monitoring", "Continuously correlate dependencies to known CVEs", priority="medium")

    if (
        bool(s.get("manipulation_detected"))
        or bool(s.get("layout_text_divergence"))
        or bool(s.get("cross_modal_mismatch"))
        or bool(s.get("ocr_yolo_label_conflict"))
        or bool(s.get("vision_yolo_conflict"))
    ):
        _add("Content Integrity Analysis", "Document/image tampering indicators detected", priority="medium")
    if bool(s.get("cross_modal_mismatch")) or bool(s.get("ocr_yolo_label_conflict")) or bool(s.get("vision_yolo_conflict")):
        _add("Multi-Model Consensus Gate", "Cross-modal identity conflict detected (YOLO/OCR/Vision mismatch)", priority="high")
        _add("Human-in-the-Loop Verification", "Escalate uncertain product identity before automated decisions", priority="high")

    # Stable dedupe by (control, priority).
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for row in out:
        key = (str(row.get("control")), str(row.get("priority")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _scenario_catalog() -> Dict[str, Dict[str, Any]]:
    # Small, deterministic library for demo. This is used to provide a per-scenario
    # breakdown of scores and mappings in decision traces.
    return {
        "email_bec": {
            "title": "Business Email Compromise / Supplier Impersonation",
            "dread_avg": 7.2,
            "cvss": {"score": 7.6, "severity": "high", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:M"},
            "stride": ["Spoofing", "Tampering"],
        },
        "email_c2": {
            "title": "Email-based C2 Beaconing",
            "dread_avg": 8.1,
            "cvss": {"score": 8.2, "severity": "high", "vector": "AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:M"},
            "stride": ["Repudiation", "InformationDisclosure"],
        },
        "prompt_injection": {
            "title": "Prompt Injection / Excessive Agency Attempt",
            "dread_avg": 7.8,
            "cvss": {"score": 8.0, "severity": "high", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:H/I:H/A:L"},
            "stride": ["ElevationOfPrivilege", "InformationDisclosure"],
        },
        "cv_doc_tamper": {
            "title": "Document/Image Manipulation (returns/invoice)",
            "dread_avg": 5.9,
            "cvss": {"score": 6.4, "severity": "medium", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:M/I:M/A:L"},
            "stride": ["Tampering"],
        },
        "cv_qr_injection": {
            "title": "QR/Barcode URL Injection",
            "dread_avg": 6.6,
            "cvss": {"score": 7.1, "severity": "high", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:M/I:H/A:L"},
            "stride": ["Spoofing", "Tampering"],
        },
        "cv_ocr_adversarial": {
            "title": "OCR Adversarial Typography / Dual-OCR Disagreement",
            "dread_avg": 6.2,
            "cvss": {"score": 6.8, "severity": "medium", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:M/I:M/A:N"},
            "stride": ["Tampering"],
        },
        "cv_multimodal_conflict": {
            "title": "Multimodal Product Identity Conflict",
            "dread_avg": 6.9,
            "cvss": {"score": 7.3, "severity": "high", "vector": "AV:N/AC:L/PR:N/UI:R/S:U/C:M/I:H/A:N"},
            "stride": ["Tampering", "Spoofing"],
        },
    }


def _pick_scenarios(*, channel: str, signals: Dict[str, Any], tags: List[str]) -> List[str]:
    tset = {str(t or "").lower() for t in (tags or [])}
    out: List[str] = []
    if channel == "email":
        if "bec" in tset or "brand_impersonation" in tset or "reply_to_mismatch" in tset:
            out.append("email_bec")
        if bool(signals.get("email_c2_beaconing")):
            out.append("email_c2")
        if bool(signals.get("prompt_injection")) or bool(signals.get("agentic_tool_abuse")):
            out.append("prompt_injection")
    elif channel == "cv":
        if bool(signals.get("manipulation_detected")):
            out.append("cv_doc_tamper")
        if bool(signals.get("qr_url_present")):
            out.append("cv_qr_injection")
        if bool(signals.get("ocr_adversarial_typography")):
            out.append("cv_ocr_adversarial")
        if bool(signals.get("cross_modal_mismatch")) or bool(signals.get("ocr_yolo_label_conflict")) or bool(signals.get("vision_yolo_conflict")):
            out.append("cv_multimodal_conflict")
    # stable dedupe
    seen = set()
    return [x for x in out if x and (x not in seen and not seen.add(x))]


def _dread_from_avg(avg: float) -> Dict[str, Any]:
    # Keep similar shape to threat_enrichment._dread
    avg = max(0.0, min(10.0, float(avg)))
    return {
        "damage": round(min(10.0, avg + 1.0), 2),
        "reproducibility": round(avg, 2),
        "exploitability": round(min(10.0, avg + 0.5), 2),
        "affected_users": round(max(1.0, avg - 0.5), 2),
        "discoverability": round(min(10.0, avg + 0.75), 2),
        "avg": round(avg, 2),
    }


def _scenario_breakdown(*, ids: List[str], mitre_atlas: List[str], mitre_attack: List[str], owasp_llm: List[str], compliance: Dict[str, Any]) -> List[Dict[str, Any]]:
    cat = _scenario_catalog()
    out: List[Dict[str, Any]] = []
    for sid in ids:
        meta = cat.get(sid) or {}
        dread = _dread_from_avg(float(meta.get("dread_avg") or 0.0)) if meta.get("dread_avg") is not None else None
        cvss = meta.get("cvss") if isinstance(meta.get("cvss"), dict) else None
        out.append(
            {
                "id": sid,
                "title": meta.get("title"),
                "mitre_attack": mitre_attack,
                "mitre_atlas": mitre_atlas,
                "owasp_llm_top10": owasp_llm,
                "stride": meta.get("stride") or [],
                "dread": dread,
                "cvss": cvss,
                "compliance": compliance,
            }
        )
    return out


def correlate_security_analysis(
    *,
    channel: str,
    severity: str | None,
    tags: List[str] | None,
    reasons: List[str] | None,
    threat_correlation: Dict[str, Any] | None,
    signals: Dict[str, Any] | None,
    evidence: Dict[str, Any] | None,
) -> Dict[str, Any]:
    tags_l = list(tags or [])
    signals_l = dict(signals or {})
    threat = threat_correlation or {}

    # Carry some common booleans into signals so mappings are consistent.
    try:
        if "dmarc" in {str(t).lower() for t in tags_l}:
            signals_l.setdefault("dmarc_fail", True)
    except Exception:
        pass

    mitre_in = threat.get("mitre_attack") if isinstance(threat.get("mitre_attack"), list) else []
    atlas, attack = _split_mitre([str(x) for x in mitre_in])
    for item in _artifact_claims(evidence or {}):
        for tag in (item.get("mitre_attack") or []):
            s = str(tag or "").strip()
            if s and s not in attack:
                attack.append(s)
        for tag in (item.get("possible_mitre_attack") or []):
            s = str(tag or "").strip()
            if s and s not in attack:
                attack.append(s)
        for tag in (item.get("mitre_atlas") or []):
            s = str(tag or "").strip()
            if s and s not in atlas:
                atlas.append(s)
        for tag in (item.get("possible_mitre_atlas") or []):
            s = str(tag or "").strip()
            if s and s not in atlas:
                atlas.append(s)
    for k, v in signals_l.items():
        if not bool(v):
            continue
        atlas_id = _SIGNAL_TO_ATLAS.get(str(k))
        attack_id = _SIGNAL_TO_ATTACK.get(str(k))
        if atlas_id and atlas_id not in atlas:
            atlas.append(atlas_id)
        if attack_id and attack_id not in attack:
            attack.append(attack_id)
    owasp_llm = map_signals_to_owasp({k: bool(v) for k, v in signals_l.items()})
    stride = _stride_from_signals(signals_l, tags_l)
    cvss = threat.get("cvss") if isinstance(threat.get("cvss"), dict) else None
    dread = threat.get("dread") if isinstance(threat.get("dread"), dict) else None
    dread_ctx = dict(dread or {})
    dread_ctx["evidence_context"] = evidence or {}
    pasta = _pasta(signals_l, severity, dread=dread_ctx)
    kev = threat.get("kev") if isinstance(threat.get("kev"), list) else []

    comp = _compliance(signals_l, tags_l)
    evidence_compliance = (evidence or {}).get("compliance") if isinstance((evidence or {}).get("compliance"), dict) else {}
    if isinstance(evidence_compliance, dict) and isinstance(evidence_compliance.get("frameworks"), list):
        merged_frameworks: List[Dict[str, Any]] = list(comp.get("frameworks") or [])
        for item in evidence_compliance.get("frameworks") or []:
            if isinstance(item, dict):
                merged_frameworks.append(item)
        comp = {"frameworks": merged_frameworks}
    d3fend = _d3fend_suggestions(signals_l, tags_l)
    scenario_ids = _pick_scenarios(channel=channel, signals=signals_l, tags=tags_l)
    scenarios = _scenario_breakdown(ids=scenario_ids, mitre_atlas=atlas, mitre_attack=attack, owasp_llm=owasp_llm, compliance=comp)
    validated_pasta_stage = _validate_pasta_stage(pasta.get("pasta_stage"))
    validated_kill_chain_stage = _validate_kill_chain_stage((dread or {}).get("kill_chain_stage"))
    framework_rows, possible_framework_rows, suppressed_framework_rows = _build_framework_rows(
        signals=signals_l,
        mitre_attack=attack,
        mitre_atlas=atlas,
        pasta_stage=validated_pasta_stage,
        compliance=comp,
        evidence=evidence or {},
    )
    visible_attack = [
        str(row.get("control_or_tag") or "")
        for row in framework_rows
        if str(row.get("framework") or "") == "MITRE ATT&CK"
    ]
    visible_atlas = [
        str(row.get("control_or_tag") or "")
        for row in framework_rows
        if str(row.get("framework") or "") == "MITRE ATLAS"
    ]
    possible_attack = [
        str(row.get("control_or_tag") or "")
        for row in possible_framework_rows
        if str(row.get("framework") or "") == "MITRE ATT&CK"
    ]
    possible_atlas = [
        str(row.get("control_or_tag") or "")
        for row in possible_framework_rows
        if str(row.get("framework") or "") == "MITRE ATLAS"
    ]
    dread_dimensions = _build_dread_dimensions(dread, evidence or {})
    evidence_quality = _dread_evidence_quality(dread)
    ocr_confidence = _ocr_confidence_from_evidence(evidence or {})
    if ocr_confidence is not None and ocr_confidence < 0.65:
        evidence_quality = {
            **evidence_quality,
            "band": "LOW" if evidence_quality.get("band") != "HIGH" else evidence_quality.get("band"),
            "label": f"{evidence_quality.get('label') or 'Evidence quality constrained'} OCR-derived evidence confidence is low ({ocr_confidence:.2f}).",
            "ocr_confidence": round(float(ocr_confidence), 3),
        }

    return {
        "severity": severity,
        "channel": channel,
        "signals": signals_l,
        "tags": tags_l,
        "reasons": list(reasons or []),
        "mitre_atlas": visible_atlas,
        "mitre_attack": visible_attack,
        "possible_mitre_atlas": possible_atlas,
        "possible_mitre_attack": possible_attack,
        "owasp_llm_top10": owasp_llm,
        "stride_categories": stride,
        "scenarios": scenarios,
        "pasta": pasta,
        "pasta_stage": validated_pasta_stage,
        "validated_pasta_stage": validated_pasta_stage,
        "validated_kill_chain_stage": validated_kill_chain_stage,
        "cvss": cvss,
        "dread": dread,
        "dread_dimensions": dread_dimensions,
        "evidence_quality": evidence_quality,
        "kev_ids": kev,
        "lev": _lev(dread, cvss),
        "sbom": _sbom_snapshot(),
        "compliance": comp,
        "framework_rows": framework_rows,
        "possible_framework_rows": possible_framework_rows,
        "suppressed_framework_rows": suppressed_framework_rows,
        "mapping_version": _FRAMEWORK_MAPPING_VERSION,
        "d3fend_suggestions": d3fend,
        "evidence": evidence or {},
    }
