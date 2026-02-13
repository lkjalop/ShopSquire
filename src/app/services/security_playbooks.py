from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.services.playbook_engine import (
    get_playbook_by_id,
    list_playbooks,
    load_playbook_config,
    select_playbook_from_tags,
)


def select_playbook(signals: Dict[str, Any], severity: str | None = None) -> Optional[Dict[str, Any]]:
    """Select a playbook from the unified config registry.

    `signals` is the Security_Observer signal map (boolean flags). We map it to
    playbook IDs via `signal_map` in `config/security/cv_playbooks.json`.
    """
    cfg = load_playbook_config()
    playbooks = cfg.get("playbooks") if isinstance(cfg.get("playbooks"), list) else []
    signal_map = cfg.get("signal_map") if isinstance(cfg.get("signal_map"), dict) else {}

    candidates: List[str] = []
    try:
        for sig, val in (signals or {}).items():
            if val is True and sig in signal_map:
                try:
                    candidates.extend(list(signal_map.get(sig) or []))
                except Exception:
                    pass
    except Exception:
        candidates = []

    # Stable ordering, dedupe
    seen = set()
    ordered = []
    for cid in candidates:
        if cid and cid not in seen:
            seen.add(cid)
            ordered.append(cid)

    for pb_id in ordered:
        pb = next((p for p in playbooks if p.get("id") == pb_id), None)
        if not pb:
            continue
        if severity and pb.get("severity") and str(pb.get("severity")).lower() != str(severity).lower():
            continue
        return pb
    # fallback: return first matching playbook by id without severity filter
    for pb_id in ordered:
        pb = next((p for p in playbooks if p.get("id") == pb_id), None)
        if pb:
            return pb
    return None


def build_evidence_snapshot(details: Dict[str, Any]) -> Dict[str, Any]:
    sec = details.get("security") if isinstance(details.get("security"), dict) else details.get("security_analysis") or {}
    risk = details.get("risk_quantification") if isinstance(details.get("risk_quantification"), dict) else {}
    return {
        "risk": risk,
        "signals": sec.get("signals") if isinstance(sec, dict) else {},
        "mitre": sec.get("mitre") or sec.get("mitre_atlas") or [],
        "owasp": sec.get("owasp") or sec.get("owasp_llm_top10") or [],
        "scores": {
            "cvss": sec.get("cvss"),
            "dread": sec.get("dread"),
            "pasta": sec.get("pasta"),
        },
        "trace_id": details.get("trace_id"),
    }


def select_cv_playbook(
    evidence_tags: List[str],
    risk_band: str | None,
) -> Optional[Dict[str, Any]]:
    return select_playbook_from_tags(evidence_tags, risk_band)


def get_cv_playbook_map() -> Dict[str, Any]:
    return load_playbook_config()


def get_cv_playbook_by_id(playbook_id: str | None) -> Optional[Dict[str, Any]]:
    return get_playbook_by_id(playbook_id)


def list_cv_playbooks(*, include_disabled: bool = True, domain: str | None = None) -> List[Dict[str, Any]]:
    return list_playbooks(include_disabled=include_disabled, domain=domain)
