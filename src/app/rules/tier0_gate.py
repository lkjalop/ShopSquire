from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.app.policy.vertical_pack import VerticalPack
from src.app.rules.image_quality import assess_image_quality
from src.app.rules.required_views import check_required_views
from src.app.rules.hash_reuse import assess_hash_reuse
from src.app.rules.barcode_decode import decode_barcodes
from src.app.rules.eligibility import evaluate_eligibility
from src.app.rules.config_defaults import eligibility_defaults, image_quality_defaults


GateDecision = Literal["proceed", "ask_more_images", "deny"]


@dataclass
class Tier0GateResult:
    decision: GateDecision
    reasons: List[str]
    details: Dict[str, Any]
    missing_views: List[str]


def run_tier0_gate(
    *,
    payload: Dict[str, Any],
    images: List[Tuple[str, bytes]],
    pack: VerticalPack,
    strict: Optional[bool] = None,
) -> Tier0GateResult:
    strict_required = pack.strict_required_views if strict is None else bool(strict)
    details: Dict[str, Any] = {"vertical_pack": {"id": pack.id, "version": pack.version}}
    reasons: List[str] = []
    missing_views: List[str] = []

    # Eligibility is the only hard deny in Tier0 (when data exists).
    elig_thresholds = dict(pack.thresholds or {})
    try:
        tenant_id = str(payload.get("tenant_id")) if payload.get("tenant_id") is not None else None
        defaults = eligibility_defaults(tenant_id=tenant_id)
        if "return_window_days" not in elig_thresholds and defaults.get("default_return_window_days") is not None:
            elig_thresholds["return_window_days"] = defaults.get("default_return_window_days")
        if "sku_blacklist" not in elig_thresholds and defaults.get("sku_blacklist") is not None:
            elig_thresholds["sku_blacklist"] = defaults.get("sku_blacklist")
    except Exception:
        pass
    elig = evaluate_eligibility(payload, thresholds=elig_thresholds, taxonomy=pack.taxonomy)
    details["eligibility"] = {"eligible": elig.eligible, "reasons": elig.reasons, "details": elig.details}
    if not elig.eligible:
        return Tier0GateResult(decision="deny", reasons=elig.reasons or ["ineligible"], details=details, missing_views=[])

    # Image quality gate: if images are too small/invalid, ask for reupload.
    iq_cfg = {}
    try:
        tenant_id = str(payload.get("tenant_id")) if payload.get("tenant_id") is not None else None
        iq_cfg = image_quality_defaults(tenant_id=tenant_id)
    except Exception:
        iq_cfg = {}
    try:
        min_bytes = int(pack.thresholds.get("image_min_bytes") or iq_cfg.get("min_bytes") or 8_000)
    except Exception:
        min_bytes = 8_000
    try:
        min_dim = int(pack.thresholds.get("image_min_dim") or iq_cfg.get("min_dim") or 128)
    except Exception:
        min_dim = 128
    try:
        min_quality = float(pack.thresholds.get("image_quality_min") or iq_cfg.get("min_quality_score") or 0.6)
    except Exception:
        min_quality = 0.6
    iq = assess_image_quality(images, min_bytes=min_bytes, min_dim=min_dim, min_quality_score=min_quality)
    details["image_quality"] = {"ok": iq.ok, "score": iq.score, "reasons": iq.reasons, "details": iq.details}
    if not iq.ok:
        reasons.extend(["image_quality_failed"] + (iq.reasons or []))
        return Tier0GateResult(decision="ask_more_images", reasons=reasons, details=details, missing_views=[])

    # Required views: advisory unless strict_required_views enabled.
    rv = check_required_views(images, pack.required_views)
    details["required_views"] = {"required": rv.required, "present": rv.present, "missing": rv.missing, "details": rv.details}
    missing_views = list(rv.missing or [])
    if strict_required and missing_views:
        reasons.append("missing_required_views")
        return Tier0GateResult(decision="ask_more_images", reasons=reasons, details=details, missing_views=missing_views)

    # Hash reuse: does not block; it is a signal for scoring/escalation.
    reuse = assess_hash_reuse(images)
    details["hash_reuse"] = {"any_reused": reuse.any_reused, "images": reuse.images}
    if reuse.any_reused:
        reasons.append("image_reuse_detected")

    # Barcode/QR decode: cheap attempt before OCR; non-blocking.
    bc = decode_barcodes(images)
    details["barcode_decode"] = {"ok": bc.ok, "codes": bc.codes, "reasons": bc.reasons}
    # Surface decoder diagnostics into the gate details for downstream visibility
    try:
        qr_reasons = getattr(bc, "reasons", []) or []
        if qr_reasons:
            diag = details.get("diagnostics") or {}
            diag.setdefault("qr_decoder", []).extend(qr_reasons)
            details["diagnostics"] = diag
    except Exception:
        import logging

        logging.getLogger("shopsquire.tier0_gate").exception("Failed to attach barcode decoder diagnostics")

    return Tier0GateResult(decision="proceed", reasons=reasons, details=details, missing_views=missing_views)
