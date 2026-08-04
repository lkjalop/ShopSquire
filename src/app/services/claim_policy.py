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


def classify_failure_severity(*, description: str = "", damage_type: str = "",
                              tenant_id: Optional[str] = None) -> Dict[str, Any]:
    """ACL major/minor failure classification → which remedy OPTIONS the buyer may be shown.

    Under the Australian Consumer Law a MAJOR failure means the CONSUMER chooses the remedy
    (refund / replacement / repair); a MINOR failure lets the supplier repair within a reasonable
    time. This classifier proposes; a human confirms on anything binding. Term lists live in
    config/rules/returns_policy.json (tenant-overridable DATA) — severity semantics, no vertical
    vocabulary in code. Safety signals always classify MAJOR and flag safety_risk.
    """
    cfg = returns_policy_defaults(tenant_id=tenant_id) or {}
    text = f"{description or ''} {damage_type or ''}".lower()

    def _hits(key: str) -> List[str]:
        return [t for t in (cfg.get(key) or []) if str(t).lower() in text]

    safety = _hits("safety_terms")
    major = _hits("major_failure_terms")
    minor = _hits("minor_failure_terms")
    if safety:
        return {"severity": "major", "safety_risk": True, "consumer_chooses": True,
                "remedy_options": ["refund", "replacement", "repair"],
                "matched_terms": safety[:4],
                "rationale": "safety signal — treated as major failure; stop-use advice + human review"}
    if major:
        return {"severity": "major", "safety_risk": False, "consumer_chooses": True,
                "remedy_options": ["refund", "replacement", "repair"],
                "matched_terms": major[:4],
                "rationale": "total/functional failure — consumer chooses the remedy (ACL major failure)"}
    if minor:
        return {"severity": "minor", "safety_risk": False, "consumer_chooses": False,
                "remedy_options": ["repair"],
                "matched_terms": minor[:4],
                "rationale": "cosmetic/minor fault — supplier may repair within a reasonable time"}
    return {"severity": "unknown", "safety_risk": False, "consumer_chooses": False,
            "remedy_options": ["assessment"],
            "matched_terms": [],
            "rationale": "severity not determinable from the claim text — assessment first"}


def _photo_datetimes(images: List) -> List[datetime]:
    """EXIF capture times (DateTimeOriginal/DateTime) from (filename, bytes) evidence images.
    Best-effort: stripped/absent EXIF yields nothing (absence is never a signal). Monkeypatchable
    in tests so forensics logic is testable without crafting EXIF blobs."""
    out: List[datetime] = []
    try:
        import io
        from PIL import Image
    except ImportError:
        return out
    for item in images or []:
        try:
            blob = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item
            exif = Image.open(io.BytesIO(blob)).getexif()
            for tag in (36867, 306):   # DateTimeOriginal, DateTime
                raw = exif.get(tag)
                if raw:
                    dt = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
                    out.append(dt)
                    break
        except Exception:
            continue
    return out


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
    images: Optional[List] = None,
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

    # ── 3b. Photo-timestamp forensics (R4 — FraudScorer's claim_before_delivery analog, fed with
    #        REAL inputs at last): an EXIF capture time BEFORE the purchase is physically impossible
    #        evidence for THIS purchase. Best-effort (EXIF is often stripped — absence proves nothing).
    if images and purchased_at is not None:
        try:
            photo_times = _photo_datetimes(images)
            if any(pt < purchased_at for pt in photo_times):
                signals.append({
                    "signal": "photo_predates_purchase",
                    "delta": _cfg_int(cfg, "photo_predates_purchase_delta", 40),
                    "detail": "evidence photo EXIF timestamp predates the corroborated purchase date",
                })
        except Exception:
            pass  # forensics are an enhancement — never block claim intake

    # ── 3c. Claim velocity: a claim within an hour of purchase is a classic abuse tempo (config) ──
    if purchased_at is not None:
        too_soon_h = _cfg_int(cfg, "claim_too_soon_hours", 1)
        age_h = (now - purchased_at).total_seconds() / 3600.0
        if 0 <= age_h < too_soon_h:
            signals.append({
                "signal": "claim_too_soon",
                "delta": _cfg_int(cfg, "claim_too_soon_delta", 15),
                "detail": f"claim {age_h:.1f}h after purchase (< {too_soon_h}h)",
            })

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
