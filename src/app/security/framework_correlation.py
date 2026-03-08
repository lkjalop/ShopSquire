from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.app.security.owasp_map import map_signals_to_owasp


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


def _stride_from_signals(signals: Dict[str, Any], tags: List[str]) -> List[str]:
    tset = {str(t or "").lower() for t in (tags or [])}
    s = signals or {}
    out: List[str] = []

    # Spoofing: impersonation, lookalikes, auth alignment failure.
    if any(k in tset for k in ("bec", "brand_impersonation", "lookalike_domain", "reply_to_mismatch")):
        out.append("Spoofing")
    if bool(s.get("dmarc_fail")) or bool(s.get("auth_alignment_failed")):
        out.append("Spoofing")
    if bool(s.get("homoglyph")) or bool(s.get("unicode_confusable")):
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

    # Repudiation: covert channels / missing audit linkage.
    if bool(s.get("email_c2_beaconing")) or bool(s.get("thread_hijack")):
        out.append("Repudiation")

    # Information disclosure: exfil / secrets / PII.
    if bool(s.get("data_exfiltration")) or bool(s.get("pii")) or bool(s.get("api_key")):
        out.append("InformationDisclosure")

    # Denial of service: burst, lock contention, rate anomalies.
    if bool(s.get("scanner_burst")) or bool(s.get("rate_anomaly")):
        out.append("DenialOfService")

    # Elevation of privilege: tool abuse / bypass attempts.
    if bool(s.get("agentic_tool_abuse")) or bool(s.get("prompt_injection")) or bool(s.get("dangerous_tool_intent")):
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
        {"id": "Stage6", "name": "RiskResponse"},
        {"id": "Stage7", "name": "MitigationVerification"},
    ]
    current = "Stage1"
    try:
        if any(bool(v) for v in (signals or {}).values()):
            current = "Stage2"
        if bool(signals.get("supply_chain")) or bool(signals.get("training_poisoning")):
            current = "Stage3"
        if bool(signals.get("jailbreak")) or bool(signals.get("prompt_injection")) or bool(signals.get("agentic_tool_abuse")):
            current = "Stage4"
        if bool(signals.get("data_exfiltration")) or bool(signals.get("pci")) or bool(signals.get("pii")):
            current = "Stage5"
        if bool(signals.get("cross_modal_mismatch")) or bool(signals.get("multimodal_attack_surface_high")):
            current = "Stage5"
        if str(severity or "").lower() in ("high", "critical", "error"):
            current = "Stage6"
        # DREAD-driven PASTA floor: weighted DREAD >= 7.5 at advanced kill-chain stage → min Stage6
        if isinstance(dread, dict):
            _dw_avg = float(dread.get("weighted_avg") or 0)
            _dw_kc = str(dread.get("kill_chain_stage") or "")
            if _dw_avg >= 7.5 and _dw_kc in ("Exploitation", "Installation", "CommandAndControl", "ActionsOnObjectives"):
                _sn = int(current.replace("Stage", "") or "1")
                if _sn < 6:
                    current = "Stage6"
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
    owasp_llm = map_signals_to_owasp({k: bool(v) for k, v in signals_l.items()})
    stride = _stride_from_signals(signals_l, tags_l)
    cvss = threat.get("cvss") if isinstance(threat.get("cvss"), dict) else None
    dread = threat.get("dread") if isinstance(threat.get("dread"), dict) else None
    pasta = _pasta(signals_l, severity, dread=dread)
    kev = threat.get("kev") if isinstance(threat.get("kev"), list) else []

    comp = _compliance(signals_l, tags_l)
    d3fend = _d3fend_suggestions(signals_l, tags_l)
    scenario_ids = _pick_scenarios(channel=channel, signals=signals_l, tags=tags_l)
    scenarios = _scenario_breakdown(ids=scenario_ids, mitre_atlas=atlas, mitre_attack=attack, owasp_llm=owasp_llm, compliance=comp)

    return {
        "severity": severity,
        "channel": channel,
        "signals": signals_l,
        "tags": tags_l,
        "reasons": list(reasons or []),
        "mitre_atlas": atlas,
        "mitre_attack": attack,
        "owasp_llm_top10": owasp_llm,
        "stride_categories": stride,
        "scenarios": scenarios,
        "pasta": pasta,
        "pasta_stage": pasta.get("pasta_stage"),
        "cvss": cvss,
        "dread": dread,
        "kev_ids": kev,
        "lev": _lev(dread, cvss),
        "sbom": _sbom_snapshot(),
        "compliance": comp,
        "d3fend_suggestions": d3fend,
        "evidence": evidence or {},
    }
