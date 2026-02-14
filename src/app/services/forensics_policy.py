from __future__ import annotations

from typing import Any, Dict, Tuple

from src.app.services.image_forensics import ForensicsResult


def evaluate(forensics: ForensicsResult, context: Dict[str, Any] | None = None, ela_mask_area_ratio: float = 0.0) -> Dict[str, Any]:
    """Evaluate a forensics verdict based on thresholds and context.

    Returns a dict: {verdict: 'approve'|'deny'|'request_more_data', reasons: [...], required_actions: [...], score: float}
    """
    ctx = context or {}
    reasons = []
    actions = []

    # Extra context (best-effort): evidence tags from Tier2 pipeline, OCR prompt-injection phrases, QR risk eval.
    evidence_tags = ctx.get("evidence_tags") if isinstance(ctx, dict) else None
    if not isinstance(evidence_tags, list):
        evidence_tags = []
    prompt_phrases = ctx.get("prompt_injection_phrases") if isinstance(ctx, dict) else None
    if not isinstance(prompt_phrases, list):
        prompt_phrases = []
    qr_risks = ctx.get("qr_risks") if isinstance(ctx, dict) else None
    if not isinstance(qr_risks, list):
        qr_risks = []

    manip = float(forensics.manipulation_score or 0.0)
    splice = float(forensics.splice_score or 0.0)
    copy_move = float(forensics.copy_move_score or 0.0)
    double_comp = float(forensics.double_compress_score or 0.0)
    blur = float(forensics.blur_score or 0.0)
    flags = set(forensics.metadata_flags or [])

    # Auto-deny
    if manip >= 0.85 or (splice >= 0.8 and ela_mask_area_ratio >= 0.08):
        reasons.append("High manipulation/splice confidence")
        return {
            "verdict": "deny",
            "reasons": reasons,
            "required_actions": [],
            "score": manip,
        }

    # Step-up / risk elevation
    if double_comp >= 0.7 and ("edited_software" in flags):
        reasons.append("Double-compression with editor EXIF flags")
        actions.extend(["otp_verification", "address_confirmation"])

    # Prompt-injection-like visible text in image is a strong signal: quarantine and require human review.
    if "prompt_injection_text_suspected" in evidence_tags or (prompt_phrases and len(prompt_phrases) > 0):
        reasons.append("Instruction-like text detected in image (possible prompt injection)")
        actions.extend(["quarantine_evidence", "human_review", "reupload_product_focused_photo"])

    # QR URLs are never auto-followed; suspicious URLs require human review.
    if "qr_url_present" in evidence_tags:
        actions.append("do_not_follow_links")
    if "qr_url_suspicious" in evidence_tags or any(float((r or {}).get("risk") or 0.0) >= 0.6 for r in (qr_risks or [])):
        reasons.append("Suspicious QR/link payload detected")
        actions.extend(["human_review", "quarantine_evidence"])

    # Category mismatch: likely wrong evidence (or adversarial upload). Ask for better images.
    if "image_category_mismatch_filename" in evidence_tags or "image_category_mismatch_expected" in evidence_tags:
        reasons.append("Image does not appear to match the described product")
        actions.extend(["upload_product_focused", "second_angle"])

    # Unicode/homoglyph filename risk (social engineering / tricking logs/users).
    if "filename_nfkc_changed" in evidence_tags or "filename_unicode_suspicious" in evidence_tags:
        reasons.append("Suspicious characters detected in filename")
        actions.append("reupload_safe_filename")

    # Order id validation (when provided by caller).
    if "order_id_not_found" in evidence_tags:
        reasons.append("Order number not found")
        actions.extend(["verify_order_id", "sign_in_to_track_orders"])

    # Blur → more evidence required
    if blur >= 0.85:
        reasons.append("Image too blurry")
        actions.extend(["upload_high_quality", "second_angle", "macro_damage_area"])

    # Default approve threshold (for CV-only use, conservative)
    if manip <= 0.25 and splice <= 0.3 and copy_move <= 0.3 and double_comp <= 0.3 and blur <= 0.6:
        reasons.append("Low-risk image characteristics")
        return {
            "verdict": "approve",
            "reasons": reasons,
            "required_actions": [],
            "score": manip,
        }

    # Request more data (nonce/live-capture, second image, etc.)
    if not actions:
        actions.extend(["upload_original_res", "second_angle", "nonce_live_capture"])
        reasons.append("Insufficient confidence for auto decision")

    return {
        "verdict": "request_more_data",
        "reasons": reasons,
        "required_actions": actions,
        "score": max(manip, splice, copy_move, double_comp, blur),
    }
