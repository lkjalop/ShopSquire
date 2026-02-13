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
