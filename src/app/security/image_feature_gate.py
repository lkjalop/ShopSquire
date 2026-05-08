"""Image Feature Gate — Policy Gate (Approach 3) for image-derived recommendation signals.

Implements the FeatureAllowlist dataclass and evaluate_image_feature_gate() function.
Called once per request, after security analysis, before retrieval.

Three trust verdicts:
  "full"       — image is clean; all signals allowed into recommendation pipeline
  "sanitized"  — image is under review; only safe structural features allowed
  "text_only"  — image is flagged/blocked; ALL image-derived features stripped

The allowlist is serialized into the decision trace so every gate decision is auditable.
Maps to: OWASP Agentic AI AA03 (Trust Boundary Violations), MAESTRO bounded influence,
         EU AI Act Art. 9 risk management, ISO 42001 AI governance.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class FeatureAllowlist:
    # Per-signal allow flags
    allow_brand_hint: bool
    allow_product_identity: bool
    allow_image_labels: bool
    allow_ocr: bool
    allow_catalog_relevance: bool
    # Verdict and audit fields
    verdict: str          # "full" | "sanitized" | "text_only"
    reason: str
    blocked_signals: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


# Signals that indicate the image carries hostile or unverified content.
_HOSTILE_REASONS = frozenset({
    "qr_external_url_detected",
    "qr_prompt_injection",
    "manipulation_detected",
    "adversarial_score_high",
    "pii_detected_ssn",
    "pii_detected",
    "ocr_prompt_injection",
    "ssn_detected",
    # OWASP Agentic AI AA05 — pixel-space prompt injection targeting vision-LLMs.
    # Detected by detect_pixel_prompt_injection() in adversarial_image_detector.py.
    "pixel_prompt_injection_suspected",
})

# Signals that are suspicious but not definitively hostile — allow catalog
# category matching but strip brand/identity signals.
_REVIEW_REASONS = frozenset({
    "qr_code_detected",
    "insufficient_image_signals",
    "steg_suspicious",
})


def evaluate_image_feature_gate(
    image_reupload_reasons: list[str],
    analysis: dict[str, Any],
) -> FeatureAllowlist:
    """Determine which image-derived features are allowed into the recommendation lane.

    Policy logic:
    - Hostile signals (QR exfil, PII, adversarial, injection) → text_only
    - Review signals (QR detected, steg, insufficient) → sanitized (labels/catalog
      allowed for category context; brand/identity stripped)
    - No signals → full
    """
    reasons_set = frozenset(str(r).lower() for r in (image_reupload_reasons or []))
    analysis_route = str((analysis or {}).get("security_route") or "").strip().lower()

    # Explicit block/flagged routes from the security analysis layer
    if analysis_route in ("block", "flagged", "hard_block"):
        return FeatureAllowlist(
            allow_brand_hint=False,
            allow_product_identity=False,
            allow_image_labels=False,
            allow_ocr=False,
            allow_catalog_relevance=False,
            verdict="text_only",
            reason=f"security_analysis_route={analysis_route}",
            blocked_signals=list(reasons_set),
        )

    # Hostile signals: strip everything image-derived
    hostile = reasons_set & _HOSTILE_REASONS
    if hostile:
        return FeatureAllowlist(
            allow_brand_hint=False,
            allow_product_identity=False,
            allow_image_labels=False,
            allow_ocr=False,
            allow_catalog_relevance=False,
            verdict="text_only",
            reason=f"hostile_signals={','.join(sorted(hostile))}",
            blocked_signals=list(reasons_set),
        )

    # Review signals: allow category context, block trust-elevating signals
    review = reasons_set & _REVIEW_REASONS
    if review or analysis_route in ("under_review", "visual_sanitized"):
        return FeatureAllowlist(
            allow_brand_hint=False,        # brand hint can steer retrieval — block
            allow_product_identity=False,  # identity match implies image trust — block
            allow_image_labels=True,       # coarse category labels are safe
            allow_ocr=False,               # OCR from unverified image is untrusted
            allow_catalog_relevance=True,  # broad category matching is safe
            verdict="sanitized",
            reason=(
                f"review_signals={','.join(sorted(review))}" if review
                else f"analysis_route={analysis_route}"
            ),
            blocked_signals=["brand_hint", "product_identity", "ocr"],
        )

    # Clean image — all signals allowed
    return FeatureAllowlist(
        allow_brand_hint=True,
        allow_product_identity=True,
        allow_image_labels=True,
        allow_ocr=True,
        allow_catalog_relevance=True,
        verdict="full",
        reason="no_security_signals",
        blocked_signals=[],
    )
