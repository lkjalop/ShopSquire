"""Claim-policy signals for return/warranty submissions — window, price sanity, evidence relevance,
serial-returner. Vertical-agnostic: all thresholds come from config/rules/returns_policy.json (tenant-
overridable); no product vocabulary lives here.

ACL POSTURE (Australian Consumer Law): none of these signals auto-deny. Consumer guarantees outlast
warranty windows ("reasonable durability"), so an out-of-window or odd-looking claim RAISES THE SCORE —
which routes it to require_human — it never rejects. Auto-approval is what these signals gate, not the
buyer's right to have the claim assessed.

Each signal is {"signal": str, "delta": int, "detail": str} — the same shape compute_return_score uses,
so the router can append them directly.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.app.rules.config_defaults import returns_policy_defaults
from src.app.services.cart_ttl import parse_timestamp


def _cfg_int(cfg: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def evaluate_claim_policy(
    *,
    corroboration: Dict[str, Any],
    claimed_value_cents: int,
    labels: Optional[List[str]] = None,
    ocr_text: str = "",
    uid: Optional[str] = None,
    tenant_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    now: Optional[datetime] = None,
    has_images: bool = False,
) -> List[Dict[str, Any]]:
    """Evaluate policy signals for a claim against its corroborated purchase. Pure except the
    serial-returner count (cases table) — every sub-check is independently best-effort."""
    cfg = returns_policy_defaults(tenant_id=tenant_id) or {}
    now = now or datetime.utcnow()
    signals: List[Dict[str, Any]] = []

    # ── 1. Purchase-age windows (needs a corroborated purchase date) ──
    purchased_at = parse_timestamp((corroboration or {}).get("purchased_at"))
    if purchased_at is not None:
        age_days = max(0, (now - purchased_at).days)
        warranty_days = _cfg_int(cfg, "warranty_window_days", 365)
        return_days = _cfg_int(cfg, "return_window_days", 30)
        if age_days > warranty_days:
            signals.append({
                "signal": "outside_warranty_window",
                "delta": _cfg_int(cfg, "outside_warranty_window_delta", 40),
                "detail": f"purchased {age_days}d ago (> {warranty_days}d warranty window) — "
                          "routed to human (ACL reasonable-durability assessment), NOT auto-denied",
            })
        elif age_days > return_days:
            signals.append({
                "signal": "outside_return_window",
                "delta": _cfg_int(cfg, "outside_return_window_delta", 25),
                "detail": f"purchased {age_days}d ago (> {return_days}d return window) — may still be a "
                          "valid warranty/guarantee claim; human review",
            })

    # ── 2. Price sanity: claimed value vs what the order actually captured ──
    try:
        order_total = int((corroboration or {}).get("total_cents") or 0)
    except (TypeError, ValueError):
        order_total = 0
    if claimed_value_cents and order_total and claimed_value_cents > order_total:
        signals.append({
            "signal": "claimed_value_exceeds_order",
            "delta": _cfg_int(cfg, "claimed_value_exceeds_order_delta", 20),
            "detail": f"claimed {claimed_value_cents}c > order total {order_total}c",
        })

    # ── 3. Evidence relevance: an off-topic photo (produce on a laptop claim) is INVALID EVIDENCE,
    #      not a subtle brand-mismatch — say so explicitly so the buyer is asked for a real photo. ──
    if has_images:
        try:
            from src.app.services.cv_triage_basic import classify_image_relevance
            relevance = classify_image_relevance(labels or [], ocr_text or "", profile_id=profile_id)
            if relevance == "off_topic":
                signals.append({
                    "signal": "invalid_evidence_off_topic",
                    "delta": _cfg_int(cfg, "off_topic_evidence_delta", 30),
                    "detail": "evidence image does not show a relevant product — "
                              "ask the buyer to photograph the actual item",
                })
        except Exception:
            pass  # relevance is an enhancement — never block claim intake on it

    # ── 4. Serial returner: N return cases for this customer inside the rolling window ──
    if uid:
        try:
            from sqlalchemy import text
            from src.app.models.db import db_session
            window_days = _cfg_int(cfg, "serial_returner_window_days", 30)
            threshold = _cfg_int(cfg, "serial_returner_threshold", 3)
            cutoff = (now - timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M:%S")
            with db_session() as db:
                n = db.execute(
                    text("SELECT COUNT(*) FROM cases WHERE customer_id = :u AND issue_type = 'return' "
                         "AND created_at >= :c"),
                    {"u": uid, "c": cutoff},
                ).scalar() or 0
            if int(n) > threshold:
                signals.append({
                    "signal": "return_pattern_abuse",
                    "delta": _cfg_int(cfg, "serial_returner_delta", 25),
                    "detail": f"{int(n)} return claims in {window_days}d (threshold {threshold})",
                })
        except Exception:
            pass  # cases table absent/unreadable → inconclusive, no penalty

    return signals
