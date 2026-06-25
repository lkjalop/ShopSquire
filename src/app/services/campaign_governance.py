"""Offers & campaigns (agnostic CORE) — LAST, and only when the safety machinery is PROVEN.

The deck is explicit: outbound offers/campaigns come last, and only after the ranking/template
experiments have demonstrated successful AUTOMATIC ROLLBACK and contact-frequency enforcement is real.
This module encodes that as a hard precondition, not a guideline:

  adaptation_readiness(db) is the gate. It returns ready=True ONLY when
    • rollback_proven      — at least one experiment has actually been reverted AND the eval safety
                             loop's heartbeat is fresh (the auto-rollback both fired and is alive), and
    • contact_freq_proven  — the contact-governance gate has actually suppressed at least one contact
                             (frequency/consent enforcement is real, not just wired).

  dispatch_campaign(db, ...) REFUSES to allow any recipient unless readiness.ready is True — a
  double-lock with the OFFERS_CAMPAIGNS_ENABLED flag. Even past the gate, every recipient must
  individually pass contact_governance.evaluate_contact (consent/frequency/region). It does NOT send:
  it returns the allow-list + per-recipient suppression reasons for a downstream connector, so this
  layer is the GOVERNED PLANNER, never the transport. Vertical-blind; best-effort; never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text


# ── readiness gate (the "offers last, only when proven" precondition) ─────────
def adaptation_readiness(db, *, eval_max_stale_seconds: float = 3600.0,
                         now_iso: Optional[str] = None) -> Dict[str, Any]:
    """Whether the adaptation machinery has PROVEN itself enough to allow outbound offers/campaigns.
    ready = rollback_proven AND contact_freq_proven. Never raises."""
    reasons: List[str] = []
    rollback_proven = False
    contact_freq_proven = False
    if db is None:
        return {"ready": False, "rollback_proven": False, "contact_freq_proven": False,
                "reasons": ["no_db"]}
    # rollback proven: an experiment was actually reverted AND the eval loop is currently alive
    try:
        from src.app.services.experiment_ops import eval_is_stale
        from src.app.services.experiments import ensure_tables
        ensure_tables(db)
        reverted = db.execute(text("SELECT COUNT(*) FROM experiment_run WHERE status='reverted'")).scalar() or 0
        loop_alive = not eval_is_stale(db, max_age_seconds=eval_max_stale_seconds, now_iso=now_iso)
        rollback_proven = bool(reverted) and bool(loop_alive)
        if not reverted:
            reasons.append("no_rollback_demonstrated")
        if not loop_alive:
            reasons.append("eval_loop_stale")
    except Exception:
        reasons.append("rollback_check_error")
    # contact-frequency proven: the gate has actually suppressed at least one contact
    try:
        from src.app.services.contact_governance import ensure_tables as _ensure_contact
        _ensure_contact(db)
        suppressed = db.execute(
            text("SELECT COUNT(*) FROM contact_audit WHERE decision='suppress'")).scalar() or 0
        contact_freq_proven = bool(suppressed)
        if not suppressed:
            reasons.append("contact_governance_not_exercised")
    except Exception:
        reasons.append("contact_check_error")
    return {"ready": bool(rollback_proven and contact_freq_proven),
            "rollback_proven": rollback_proven, "contact_freq_proven": contact_freq_proven,
            "reasons": reasons}


# ── typed offer proposals (log-only, like shadow actions) ─────────────────────
@dataclass(frozen=True)
class OfferProposal:
    offer_type: str            # opaque label (promo / bundle / winback / ...)
    target_ref: Optional[str]  # segment / entity / None
    rationale: str
    params: Dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"   # never 'dispatched' here


def propose_offers_from_findings(findings: Optional[Iterable[Any]]) -> List[OfferProposal]:
    """Map findings → offer PROPOSALS (pure; log-only). A demand spike proposes a promo on the entity;
    a conversion drop proposes a win-back. Opaque — no product vocabulary. Dispatch is a separate,
    gated, consented step."""
    out: List[OfferProposal] = []
    for f in (findings or []):
        ftype = str(getattr(f, "finding_type", None) or (f.get("finding_type") if isinstance(f, dict) else "") or "").strip()
        ent = getattr(f, "entity_ref", None) if not isinstance(f, dict) else f.get("entity_ref")
        summ = getattr(f, "summary", None) if not isinstance(f, dict) else f.get("summary")
        if ftype == "demand_shift":
            out.append(OfferProposal("promo", ent, str(summ or ftype), {"reason": "demand_shift"}))
        elif ftype == "conversion_anomaly":
            out.append(OfferProposal("winback", ent, str(summ or ftype), {"reason": "conversion_anomaly"}))
    return out


# ── governed dispatch (planner, not transport) ────────────────────────────────
def dispatch_campaign(
    db,
    *,
    recipients: Iterable[str],
    channel: str,
    campaign_id: str,
    region: str = "default",
    now_iso: Optional[str] = None,
    per_window: int = 1,
    window_seconds: int = 86400,
    region_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    tenant_id: str = "default",
    require_readiness: bool = True,
    eval_max_stale_seconds: float = 3600.0,
) -> Dict[str, Any]:
    """Plan a campaign send: returns who WOULD be contacted (passed the readiness gate AND the
    per-recipient contact-governance gate) and who is suppressed + why. Sends NOTHING — a connector
    consumes the allow-list and is the only thing that calls contact_governance.record_contact() after
    a real send. Blocked entirely until the safety machinery is proven."""
    readiness = adaptation_readiness(db, eval_max_stale_seconds=eval_max_stale_seconds, now_iso=now_iso)
    if require_readiness and not readiness.get("ready"):
        return {"allowed": [], "suppressed": [], "blocked_by_readiness": True, "readiness": readiness}

    from src.app.services.contact_governance import evaluate_contact
    allowed: List[str] = []
    suppressed: List[Dict[str, str]] = []
    for uid in recipients or []:
        if not uid:
            continue
        d = evaluate_contact(db, uid_hash=str(uid), channel=channel, campaign_id=campaign_id, region=region,
                             now_iso=now_iso, per_window=per_window, window_seconds=window_seconds,
                             region_rules=region_rules, tenant_id=tenant_id)
        if d.allowed:
            allowed.append(str(uid))
        else:
            suppressed.append({"uid": str(uid), "reason": d.reason})
    return {"allowed": allowed, "suppressed": suppressed, "blocked_by_readiness": False, "readiness": readiness}
