"""Image-security assessment and response projection; no product-fit authority."""
from typing import Any, Dict, List, Optional
from src.app.services.decision_log import log_trace_event
from src.app.security.dread_scorer import compute_dread
from src.app.security.framework_correlation import correlate_security_analysis
from src.app.security.qr_legitimacy import derive_qr_legitimacy_details


def _derive_attack_intent_and_repercussions(cv_signals: Dict[str, Any] | None) -> tuple[str, str]:
    """Map detected CV signals to a plain-English attacker intent + likely repercussions.

    Briefs the human SOC reviewer on *why* an upload was flagged and what could go
    wrong if the image-derived signals were trusted blindly.
    """
    s = cv_signals if isinstance(cv_signals, dict) else {}
    intents: List[str] = []
    repercussions: List[str] = []
    if s.get("qr_prompt_injection") or s.get("qr_external_url_detected") or s.get("qr_code_detected"):
        intents.append(
            "QR-borne indirect prompt injection / redirect to an external "
            "(possible credential-harvest or malware) URL"
        )
        repercussions.append(
            "agent goal hijack, shopper redirected to a malicious site, possible "
            "credential/account compromise"
        )
    if s.get("ocr_prompt_injection"):
        intents.append("text-in-image prompt injection to override system instructions")
        repercussions.append("policy bypass, unauthorised tool or action execution by the agent")
    if s.get("steg_suspicious"):
        intents.append("steganographic payload smuggling (covert data/command channel)")
        repercussions.append("covert data exfiltration or staged second-stage payload delivery")
    if float(s.get("adversarial_score") or 0.0) >= 0.5:
        intents.append("adversarial perturbation crafted to evade the CV classifiers")
        repercussions.append("model evasion, mislabelled product, downstream fraud")
    if s.get("manipulation_detected"):
        intents.append("image manipulation / forgery")
        repercussions.append("return or warranty fraud, fabricated evidence")
    if s.get("encoded_payload_detected") or s.get("polyglot_suspected"):
        intents.append("encoded / polyglot file payload (a file valid as two formats at once)")
        repercussions.append("parser confusion, sandbox escape, malware delivery")
    if not intents:
        intents.append("untrusted or anomalous image upload")
        repercussions.append("elevated review required before any image-derived signal can be trusted")
    return "; ".join(intents), "; ".join(repercussions)


def _summarize_recognized_product(labels: List[str] | None) -> Optional[str]:
    """Best-effort short human label for what the image shows, from SAFE visual labels.

    Lets us keep shopping context in the user-facing message even when the image
    was flagged — we still recognised the product, we just quarantined the
    malicious channel (QR/OCR/steg). Returns None when nothing is recognisable.
    """
    toks = [str(x).lower() for x in (labels or []) if str(x).strip()]
    if not toks:
        return None
    blob = " ".join(toks)
    _is_gaming = any(
        t in blob for t in ("gaming", "rog", "legion", "raider", "predator", "nitro", "alienware", "omen", "tuf")
    )
    if any(t in blob for t in ("laptop", "notebook", "macbook")):
        return "gaming laptop" if _is_gaming else "laptop"
    if any(t in blob for t in ("desktop", "tower", "workstation")) or "pc" in toks:
        return "gaming PC" if _is_gaming else "desktop PC"
    if any(t in blob for t in ("phone", "smartphone", "iphone")):
        return "phone"
    if any(t in blob for t in ("tablet", "ipad")):
        return "tablet"
    if any(t in blob for t in ("monitor", "display", "screen")):
        return "monitor"
    if any(t in blob for t in ("headphone", "headset", "earphone")):
        return "headset"
    return toks[0]


def _assess_image_compromise_breach(
    *,
    merged_text: str,
    cv_signals: Dict[str, Any] | None,
    source_ip: str | None,
    uid: str | None,
    image_hash: str | None,
    posture: Dict[str, Any],
    request: Any = None,
) -> Dict[str, Any]:
    """Run a synchronous breach assessment for a compromised image upload.

    Enriches the requester IP via ASN/GeoIP (known-bad-actor scoring), maps the
    attack to MITRE ATLAS / OWASP tags, and notifies humans by persisting a
    security event that auto-routes to an incident + WORM audit. Returns a
    structured summary for the chat response.

    NEVER blocks the recommendation — this is the warn-and-continue path.
    """
    from src.app.security.observer import analyze_payload, emit_security_event

    intent, repercussions = _derive_attack_intent_and_repercussions(cv_signals)
    sec_payload: Dict[str, Any] = {
        "query": str(merged_text or "")[:1000],
        "source": "chat_image_compromise",
    }
    if source_ip:
        sec_payload["ip"] = source_ip
    if uid:
        sec_payload["uid"] = uid
    if cv_signals:
        sec_payload["cv_signals"] = cv_signals

    severity = str(posture.get("severity") or "high")
    details: Dict[str, Any] = {}
    try:
        analysis = analyze_payload(sec_payload)
        if isinstance(analysis, dict):
            severity = str(analysis.get("severity") or severity)
            details = analysis.get("details") if isinstance(analysis.get("details"), dict) else {}
    except Exception:
        details = {}

    geo: Dict[str, Any] = {}
    signals: Dict[str, Any] = {}
    try:
        geo = ((details.get("network") or {}).get("geo")) or {}
        signals = details.get("signals") or {}
    except (AttributeError, TypeError):
        geo, signals = {}, {}

    # Known-bad-actor determination via ASN / GeoIP risk.
    bad_asn: set = set()
    try:
        from src.app.security.observer import _load_bad_asn
        bad_asn = set(_load_bad_asn())
    except Exception:
        bad_asn = set()
    is_bad_actor = bool(
        signals.get("ip_risk")
        or float(geo.get("risk") or 0.0) >= 0.7
        or geo.get("is_hosting")
        or geo.get("is_vpn")
        or (geo.get("asn") in bad_asn if geo.get("asn") is not None else False)
    )
    ip_assessment = {
        "ip_hash": ((details.get("network") or {}).get("ip_hash")),
        "asn": geo.get("asn"),
        "asn_org": geo.get("asn_org"),
        "country": geo.get("country"),
        "is_hosting": bool(geo.get("is_hosting")),
        "is_vpn": bool(geo.get("is_vpn")),
        "risk": float(geo.get("risk") or 0.0),
        "known_bad_actor": is_bad_actor,
        "geo_country_mismatch": bool(signals.get("geo_country_mismatch")),
    }

    # Notify humans: persist a security event that auto-routes to an incident + WORM.
    human_notified = False
    try:
        emit_security_event(
            path="/api/v1/chat/image-compromise",
            payload={
                **sec_payload,
                "attack_intent": intent,
                "repercussions": repercussions,
                "image_hash": str(image_hash or "")[:64],
                "ip_assessment": ip_assessment,
            },
            request=request,
        )
        human_notified = True
    except Exception:
        human_notified = False

    assessment = {
        "severity": severity,
        "attack_intent": intent,
        "potential_repercussions": repercussions,
        "ip_assessment": ip_assessment,
        "mitre_atlas": (details.get("mitre_atlas") or [])[:8],
        "owasp_llm_top10": (details.get("owasp_llm_top10") or [])[:8],
        "owasp_agentic_top10": (details.get("owasp_agentic_top10") or [])[:8],
        "human_notified": human_notified,
        "route": str(posture.get("route") or "escalate"),
    }
    try:
        log_trace_event(
            trace_id=None,
            event_type="image_compromise_breach_assessment",
            source_type="agent",
            source_id="Security_Observer_Agent",
            target_type="chat",
            target_id=uid,
            payload={
                "severity": severity,
                "attack_intent": intent,
                "known_bad_actor": is_bad_actor,
                "asn": geo.get("asn"),
                "country": geo.get("country"),
                "image_hash": str(image_hash or "")[:64],
            },
        )
    except Exception:
        pass
    return assessment


def _derive_qr_details(sig: Dict[str, Any] | None, posture: Dict[str, Any] | None = None) -> Dict[str, Any]:
    p = posture if isinstance(posture, dict) else {}
    route = str(p.get("route") or "allow")
    return derive_qr_legitimacy_details(sig, policy_route=route)


def _image_trust_channels(posture: Dict[str, Any] | None) -> Dict[str, bool]:
    posture = posture or {}
    route = str(posture.get("route") or "allow")
    if posture.get("analysis_pending"):
        return {"visual_embedding_trusted": False, "ocr_trusted": False, "qr_trusted": False}
    if posture.get("analysis_degraded") and not posture.get("security_risk"):
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    if route == "allow":
        return {"visual_embedding_trusted": True, "ocr_trusted": True, "qr_trusted": True}
    if route == "visual_sanitized":
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    if route == "escalate":
        return {"visual_embedding_trusted": True, "ocr_trusted": False, "qr_trusted": False}
    return {"visual_embedding_trusted": False, "ocr_trusted": False, "qr_trusted": False}


def _frameworks_for_image_security(*, signals: Dict[str, Any], severity: str) -> Dict[str, Any]:
    norm = {str(k): bool(v) for k, v in (signals or {}).items()}
    dread = compute_dread(signals={}, cv_signals=norm, severity=severity or "warn")
    corr = correlate_security_analysis(
        channel="image",
        severity=severity,
        tags=[],
        reasons=[],
        threat_correlation={"mitre_attack": [], "dread": dread},
        signals=norm,
        evidence={},
    )
    return {
        "mitre_atlas": corr.get("mitre_atlas") or [],
        "mitre_attack": corr.get("mitre_attack") or [],
        "owasp_llm_top10": corr.get("owasp_llm_top10") or [],
        "stride_categories": corr.get("stride_categories") or [],
        "pasta": corr.get("pasta") or {},
        "pasta_stage": corr.get("pasta_stage"),
        "dread": dread,
        "cvss": corr.get("cvss") or {},
        "compliance": corr.get("compliance") or {},
        "lev": corr.get("lev") or {},
    }
