"""Attack campaign correlator.

Detects multi-pronged attack campaigns by correlating seemingly unrelated
security events that share an entity key (IP+ASN+UID hash) within a
sliding time window.

When signal diversity >= 3 AND kill-chain stage progression >= 1 within
the window, a campaign is detected.  The correlator boosts DREAD
(reproducibility +2.0, damage +1.5) and auto-advances PASTA to min Stage5.

Requires NO new infrastructure — reads from the existing
``decision_trace_events`` table.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from src.app.security.dread_scorer import _KILL_CHAIN_ORDER, _clamp

_log = logging.getLogger("shopsquire.campaign_correlator")

# Signal categories: group signals into abstract buckets so
# "prompt_injection" and "jailbreak" don't double-count as "2 categories".
_SIGNAL_CATEGORY: Dict[str, str] = {
    "prompt_injection": "llm_attack",
    "jailbreak": "llm_attack",
    "agentic_tool_abuse": "llm_attack",
    "unexpected_code_exec": "llm_attack",
    "data_exfiltration": "data_leak",
    "pci": "data_leak",
    "pii": "data_leak",
    "api_key": "data_leak",
    "scanner_burst": "recon",
    "rate_anomaly": "recon",
    "ip_risk": "recon",
    "identity_abuse": "social_eng",
    "social_engineering": "social_eng",
    "unicode_obfuscation": "evasion",
    "embedding_weakness": "evasion",
    "training_poisoning": "supply_chain",
    "supply_chain": "supply_chain",
    "email_c2_beaconing": "c2",
    "cascading_failure": "impact",
    "model_dos": "impact",
    "manipulation_detected": "cv_attack",
    "adversarial_detected": "cv_attack",
    "qr_prompt_injection": "cv_attack",
    "ocr_prompt_injection": "cv_attack",
    "steg_suspicious": "cv_attack",
}


def entity_key(ip: str | None, asn: str | None, uid_hash: str | None) -> str:
    """Deterministic hash of (IP, ASN, UID) for correlation."""
    raw = f"{ip or ''}|{asn or ''}|{uid_hash or ''}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _signal_categories(signals: Dict[str, bool]) -> set[str]:
    cats: set[str] = set()
    for sig, active in signals.items():
        if active:
            cats.add(_SIGNAL_CATEGORY.get(sig, sig))
    return cats


def _stage_index(stage: str) -> int:
    if stage in _KILL_CHAIN_ORDER:
        return _KILL_CHAIN_ORDER.index(stage)
    return 0


class CampaignCheckResult:
    __slots__ = ("detected", "campaign_id", "signal_diversity", "stage_progression",
                 "stages_seen", "categories_seen", "event_count",
                 "dread_boost_damage", "dread_boost_repro", "pasta_floor")

    def __init__(self) -> None:
        self.detected: bool = False
        self.campaign_id: Optional[str] = None
        self.signal_diversity: int = 0
        self.stage_progression: int = 0
        self.stages_seen: List[str] = []
        self.categories_seen: List[str] = []
        self.event_count: int = 0
        self.dread_boost_damage: float = 0.0
        self.dread_boost_repro: float = 0.0
        self.pasta_floor: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detected": self.detected,
            "campaign_id": self.campaign_id,
            "signal_diversity": self.signal_diversity,
            "stage_progression": self.stage_progression,
            "stages_seen": self.stages_seen,
            "categories_seen": self.categories_seen,
            "event_count": self.event_count,
            "dread_boost_damage": self.dread_boost_damage,
            "dread_boost_repro": self.dread_boost_repro,
            "pasta_floor": self.pasta_floor,
        }


def check_campaign(
    *,
    ek: str,
    current_signals: Dict[str, bool],
    current_kill_chain_stage: str,
    window_hours: int = 24,
) -> CampaignCheckResult:
    """Check if the current event is part of a larger attack campaign.

    Queries ``decision_trace_events`` for prior events sharing the same
    entity key within the window.  If combined signal diversity and
    kill-chain progression meet thresholds, a campaign is detected.
    """
    result = CampaignCheckResult()
    try:
        from src.app.models.db import db_session
        from sqlalchemy import text as sql_text

        # Gather prior events within window
        with db_session() as db:
            rows = db.execute(
                sql_text(
                    "SELECT payload FROM decision_trace_events "
                    "WHERE event_type = 'security_scan' "
                    "AND created_at >= datetime('now', :window) "
                    "ORDER BY created_at DESC LIMIT 200"
                ),
                {"window": f"-{window_hours} hours"},
            ).fetchall()

        # Filter to events matching our entity key
        import json
        all_categories: set[str] = set()
        all_stages: set[str] = set()
        matching_events = 0

        for (raw,) in (rows or []):
            try:
                payload = json.loads(raw) if isinstance(raw, str) else (raw if isinstance(raw, dict) else {})
            except Exception:
                continue
            ev_ek = str(payload.get("entity_key") or "").strip()
            if ev_ek != ek:
                continue
            matching_events += 1
            ev_signals = payload.get("signals") or {}
            all_categories |= _signal_categories(ev_signals)
            ev_stage = str(payload.get("dread_kill_chain_stage") or payload.get("kill_chain_stage") or "")
            if ev_stage:
                all_stages.add(ev_stage)

        # Include current event
        all_categories |= _signal_categories(current_signals)
        if current_kill_chain_stage:
            all_stages.add(current_kill_chain_stage)
        matching_events += 1

        result.event_count = matching_events
        result.signal_diversity = len(all_categories)
        result.categories_seen = sorted(all_categories)

        # Compute stage progression (max - min index)
        stage_indices = [_stage_index(s) for s in all_stages if s in _KILL_CHAIN_ORDER]
        if stage_indices:
            result.stage_progression = max(stage_indices) - min(stage_indices)
            result.stages_seen = sorted(all_stages, key=lambda s: _stage_index(s))

        # Detection thresholds
        if result.signal_diversity >= 3 and result.stage_progression >= 1:
            result.detected = True
            result.campaign_id = f"CAMP-{uuid.uuid4().hex[:12]}"
            result.dread_boost_repro = 2.0
            result.dread_boost_damage = 1.5
            result.pasta_floor = "Stage5"

    except Exception:
        _log.debug("campaign correlator check failed", exc_info=True)

    return result


def apply_campaign_boost(dread: Dict[str, Any], campaign: CampaignCheckResult) -> Dict[str, Any]:
    """Apply campaign-detected DREAD boosts to an existing DREAD result dict."""
    if not campaign.detected:
        return dread
    boosted = dict(dread)
    boosted["damage"] = round(_clamp(float(dread.get("damage", 0)) + campaign.dread_boost_damage), 2)
    boosted["reproducibility"] = round(_clamp(float(dread.get("reproducibility", 0)) + campaign.dread_boost_repro), 2)
    # Recompute averages
    d, r, e, a, disc = (
        boosted["damage"], boosted["reproducibility"],
        float(boosted.get("exploitability", 0)),
        float(boosted.get("affected_users", 0)),
        float(boosted.get("discoverability", 0)),
    )
    boosted["avg"] = round((d + r + e + a + disc) / 5.0, 2)
    # Recompute weighted avg using kill-chain stage
    from src.app.security.dread_scorer import _weighted_avg
    stage = str(boosted.get("kill_chain_stage") or "Reconnaissance")
    boosted["weighted_avg"] = _weighted_avg(d, r, e, a, disc, stage)
    # Append campaign evidence
    ev = list(boosted.get("evidence") or [])
    ev.append({
        "signal": "attack_campaign_detected",
        "component": "reproducibility",
        "contribution": campaign.dread_boost_repro,
        "mitre": "T1583",
        "owasp": "",
        "kill_chain": "multi-stage",
        "source": "campaign_correlator",
        "campaign_id": campaign.campaign_id,
        "event_count": campaign.event_count,
        "signal_diversity": campaign.signal_diversity,
        "stage_progression": campaign.stage_progression,
    })
    ev.append({
        "signal": "attack_campaign_detected",
        "component": "damage",
        "contribution": campaign.dread_boost_damage,
        "mitre": "T1583",
        "owasp": "",
        "kill_chain": "multi-stage",
        "source": "campaign_correlator",
        "campaign_id": campaign.campaign_id,
    })
    boosted["evidence"] = ev
    boosted["campaign"] = campaign.to_dict()
    return boosted
