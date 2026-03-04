from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.app.services.playbook_engine import (
    get_playbook_by_id,
    list_playbooks,
    load_playbook_config,
    select_playbook_from_tags,
)


_RISK_ORDER = ["low", "medium", "high", "critical"]


def _risk_rank(band: str | None) -> int:
    b = str(band or "").strip().lower()
    try:
        return _RISK_ORDER.index(b)
    except ValueError:
        return 0


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
    if not ordered:
        return None

    by_id = {str(p.get("id") or ""): p for p in playbooks if isinstance(p, dict)}
    wanted_rank = _risk_rank(severity) if severity else None

    ranked: List[tuple[int, int, int, str, Dict[str, Any]]] = []
    for pb_id in ordered:
        pb = by_id.get(str(pb_id))
        if not pb:
            continue
        if not bool(pb.get("enabled", True)):
            continue
        min_rank = _risk_rank(pb.get("risk_band_min"))
        if wanted_rank is not None and min_rank > wanted_rank:
            # Requested severity is lower than this playbook's minimum risk band.
            continue
        exact_severity = 1 if severity and str(pb.get("severity") or "").lower() == str(severity).lower() else 0
        priority = int(pb.get("priority") or 100)
        ranked.append((exact_severity, min_rank, -priority, str(pb.get("id") or ""), pb))

    if ranked:
        ranked.sort(reverse=True)
        return ranked[0][4]

    # Fallback: return first existing (enabled) playbook for compatibility.
    for pb_id in ordered:
        pb = by_id.get(str(pb_id))
        if pb and bool(pb.get("enabled", True)):
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
