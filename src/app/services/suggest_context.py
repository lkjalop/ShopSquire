"""SuggestContext — shared state object threaded through recommend pipeline stages.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
This entire module is CORE (vertical-agnostic):
  • SuggestContext — generic state container. No product-type assumptions.
  • parse_image_inputs() — parses CV signal JSON into structured dicts.
    The fields it reads (qr_code, manipulation, adversarial, pii) are
    universal image-safety signals, not product-type-specific.

Nothing in this module needs to change for pharmacy/fashion verticals.
"""
from __future__ import annotations

import time
import os
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.app.deps import scrub_pii


@dataclass
class SuggestContext:
    """Mutable context object passed through recommend pipeline stages."""

    # ── Request inputs ───────────────────────────────────────────────────────
    uid: str = ""
    uid_hash: str = "unknown"
    query: str = ""
    query_effective: str = ""
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None
    source_ip: Optional[str] = None
    trace_id: str = ""
    route_t0: float = 0.0

    # ── Image context ────────────────────────────────────────────────────────
    image_context: Dict[str, Any] = field(default_factory=lambda: {
        "labels": [], "ocr": "", "hash": None, "intent": None, "product_identity": {},
    })
    image_cv_signals_parsed: Dict[str, Any] = field(default_factory=dict)
    image_reupload_reasons: List[str] = field(default_factory=list)
    incoming_image_payload: bool = False

    # ── Security / guard state ───────────────────────────────────────────────
    guard: Dict[str, Any] = field(default_factory=dict)
    analysis: Dict[str, Any] = field(default_factory=lambda: {
        "severity": "info", "details": {"signals": {}, "reason": "pending"},
    })
    severity: str = "info"
    benign_shopping_query: bool = True

    # ── Feature flags / config ───────────────────────────────────────────────
    flags: Dict[str, Any] = field(default_factory=dict)
    skip_recommend_observer: bool = False
    fast_path_enabled: bool = False

    # ── Catalog ──────────────────────────────────────────────────────────────
    catalog_profile: Dict[str, Any] = field(default_factory=dict)
    catalog_relevance: Dict[str, Any] = field(default_factory=dict)

    # ── Timing ───────────────────────────────────────────────────────────────
    timing_breakdown: Dict[str, Any] = field(default_factory=lambda: {"ollama_summary_ms": None})

    # ── Fraud / risk ─────────────────────────────────────────────────────────
    fraud_summary: Dict[str, Any] = field(default_factory=dict)


def parse_image_inputs(
    *,
    image_labels: Optional[str],
    image_ocr_text: Optional[str],
    image_hash: Optional[str],
    image_intent: Optional[str],
    image_product_identity: Optional[str],
    image_cv_signals: Optional[str],
    image_reupload_reasons: List[str],
    _augment_fn=None,
) -> tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Parse raw image input strings into structured context + CV signals.

    Returns (image_context, image_cv_signals_parsed, image_reupload_reasons).
    Raises no exceptions — returns safe defaults on parse failure.
    """
    image_context: Dict[str, Any] = {
        "labels": [], "ocr": "", "hash": None, "intent": None, "product_identity": {},
    }
    image_cv_signals_parsed: Dict[str, Any] = {}
    reasons = list(image_reupload_reasons)

    try:
        if image_labels:
            labels = [s.strip() for s in str(image_labels).split(",") if str(s).strip()]
            image_context["labels"] = labels[:12]
        if image_ocr_text:
            image_context["ocr"] = str(image_ocr_text)[:500]
        if image_hash:
            image_context["hash"] = str(image_hash)[:128]
        if image_intent:
            image_context["intent"] = str(image_intent)[:32]
        if image_product_identity:
            parsed_pi = json.loads(str(image_product_identity))
            if isinstance(parsed_pi, dict):
                image_context["product_identity"] = parsed_pi
        if image_cv_signals:
            parsed_cv = json.loads(str(image_cv_signals))
            if isinstance(parsed_cv, dict):
                damage_score = 0.0
                try:
                    damage_score = float(parsed_cv.get("damage_score") or 0.0)
                except Exception:
                    damage_score = 0.0
                qr_detected = bool(
                    parsed_cv.get("qr_code_detected")
                    or parsed_cv.get("qr_detected")
                    or parsed_cv.get("qr_url_present")
                    or parsed_cv.get("qr_url_suspicious")
                )
                qr_external = bool(
                    parsed_cv.get("qr_external_url_detected")
                    or parsed_cv.get("qr_external_url")
                    or parsed_cv.get("qr_url_present")
                    or parsed_cv.get("qr_url_suspicious")
                )
                qr_injection = bool(
                    parsed_cv.get("qr_prompt_injection")
                    or parsed_cv.get("prompt_injection_text_suspected")
                )
                manipulation = bool(
                    parsed_cv.get("manipulation_detected")
                    or parsed_cv.get("adversarial_detected")
                    or parsed_cv.get("steg_suspicious")
                    or parsed_cv.get("duplicate_image_detected")
                )
                adversarial = float(parsed_cv.get("adversarial_score") or 0.0)
                image_cv_signals_parsed = {
                    "qr_code_detected": qr_detected,
                    "qr_prompt_injection": qr_injection,
                    "qr_external_url_detected": qr_external,
                    "ocr_prompt_injection": bool(parsed_cv.get("ocr_prompt_injection")),
                    "manipulation_detected": manipulation,
                    "adversarial_score": adversarial,
                    "intent_cv_triage": bool(parsed_cv.get("intent_cv_triage")),
                    "damage_score": damage_score,
                    "steg_suspicious": bool(parsed_cv.get("steg_suspicious")),
                    "pii_detected": bool(parsed_cv.get("pii_detected")),
                    "ssn_detected": bool(parsed_cv.get("ssn_detected")),
                    "fast_triage_timeout": bool(parsed_cv.get("fast_triage_timeout")),
                    "ssn_count": int(parsed_cv.get("ssn_count") or 0) if parsed_cv.get("ssn_count") is not None else 0,
                    "qr_payload_types": parsed_cv.get("qr_payload_types") if isinstance(parsed_cv.get("qr_payload_types"), list) else [],
                    "qr_payloads": parsed_cv.get("qr_payloads") if isinstance(parsed_cv.get("qr_payloads"), list) else [],
                    "qr_redirect_probe": parsed_cv.get("qr_redirect_probe") if isinstance(parsed_cv.get("qr_redirect_probe"), dict) else {},
                    "image_relevance": str(parsed_cv.get("image_relevance") or "relevant"),
                    "image_relevance_note": str(parsed_cv.get("image_relevance_note") or ""),
                }
                if not image_context.get("intent") and image_cv_signals_parsed.get("intent_cv_triage"):
                    image_context["intent"] = "cv_triage"
                if qr_detected:
                    reasons.append("qr_code_detected")
                if qr_external:
                    reasons.append("qr_external_url_detected")
                _already_quarantined = bool(parsed_cv.get("qr_quarantined"))
                if qr_injection and not _already_quarantined:
                    reasons.append("qr_prompt_injection")
                elif qr_injection and _already_quarantined:
                    reasons.append("qr_code_detected")
                if manipulation:
                    reasons.append("manipulation_detected")
                if adversarial >= 0.35:
                    reasons.append("adversarial_score_high")
                if bool(parsed_cv.get("ssn_detected")):
                    reasons.append("pii_detected_ssn")
                elif bool(parsed_cv.get("pii_detected")):
                    reasons.append("pii_detected")
                if bool(parsed_cv.get("fast_triage_timeout")):
                    reasons.append("fast_triage_timeout")
        if image_context.get("ocr") and _augment_fn:
            ocr_aug = _augment_fn(image_context.get("ocr"))
            for _k, _v in ocr_aug.items():
                if _v:
                    image_cv_signals_parsed[_k] = True
                    reasons.append(_k)
    except Exception:
        image_context = {"labels": [], "ocr": "", "hash": None, "intent": None}
        image_cv_signals_parsed = {}
        reasons = list(image_reupload_reasons)

    return image_context, image_cv_signals_parsed, reasons
