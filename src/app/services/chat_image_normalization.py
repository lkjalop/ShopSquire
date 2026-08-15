"""Bounded, authority-free normalization of chat image transport payloads."""
from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any


_BOOLEAN_SIGNALS = (
    "qr_code_detected", "qr_prompt_injection", "qr_external_url_detected",
    "ocr_prompt_injection", "manipulation_detected", "damage_detected",
    "steg_suspicious", "encoded_payload_detected", "polyglot_suspected",
    "payment_social_engineering", "pci_card_exposed", "crypto_payment_uri",
    "ransomware_indicator", "homoglyph_injection", "invisible_text_suspected",
    "ocr_low_confidence_uncertain",
)


def extract_image_cv_signals(image_obj: dict[str, Any] | None) -> dict[str, Any]:
    image = image_obj if isinstance(image_obj, dict) else {}
    security = image.get("security") if isinstance(image.get("security"), dict) else {}
    signals: dict[str, Any] = {}
    for candidate in (image.get("cv_signals"), security.get("signals"), security.get("cv_signals")):
        if isinstance(candidate, dict):
            signals.update(candidate)
    for key, value in security.items():
        if isinstance(value, bool):
            signals[key] = value
    for key in _BOOLEAN_SIGNALS:
        if isinstance(image.get(key), bool):
            signals[key] = bool(image[key])
    reasons = [
        str(value)
        for rows in (image.get("reasons"), security.get("reasons"))
        if isinstance(rows, list)
        for value in rows
    ]
    qr_data = image.get("qr_data")
    qr_data_present = bool(
        isinstance(qr_data, str) and qr_data.strip()
        or isinstance(qr_data, list) and qr_data
    )
    return {
        "qr_code_detected": bool(
            qr_data_present or signals.get("qr_code_detected") or signals.get("qr_detected")
            or signals.get("qr_url_present") or signals.get("qr_url_suspicious")
            or "qr_code_detected" in reasons
        ),
        "qr_prompt_injection": bool(
            signals.get("qr_prompt_injection")
            or signals.get("prompt_injection_text_suspected")
            or "qr_prompt_injection" in reasons
        ),
        "qr_external_url_detected": bool(
            signals.get("qr_external_url_detected") or signals.get("qr_external_url")
            or signals.get("qr_url_present") or signals.get("qr_url_suspicious")
            or "qr_external_url_detected" in reasons
        ),
        "ocr_prompt_injection": bool(signals.get("ocr_prompt_injection")),
        "manipulation_detected": bool(
            signals.get("manipulation_detected") or signals.get("adversarial_detected")
            or signals.get("steg_suspicious") or signals.get("duplicate_image_detected")
            or "manipulation_detected" in reasons
        ),
        "adversarial_score": float(signals.get("adversarial_score") or 0.0),
        "steg_suspicious": bool(signals.get("steg_suspicious")),
        "ocr_low_confidence_uncertain": bool(signals.get("ocr_low_confidence_uncertain")),
        "qr_payloads": list(signals.get("qr_payloads") or [])[:12]
        if isinstance(signals.get("qr_payloads"), list) else [],
        "qr_payload_types": list(signals.get("qr_payload_types") or [])[:12]
        if isinstance(signals.get("qr_payload_types"), list) else [],
        "qr_redirect_probe": dict(signals.get("qr_redirect_probe") or {})
        if isinstance(signals.get("qr_redirect_probe"), dict) else {},
    }


def extract_image_product_identity(image_obj: dict[str, Any] | None) -> dict[str, Any]:
    image = image_obj if isinstance(image_obj, dict) else {}
    security = image.get("security") if isinstance(image.get("security"), dict) else {}
    identity = image.get("product_identity") or security.get("product_identity")
    return dict(identity) if isinstance(identity, dict) else {}


def decode_image_b64(image_obj: dict[str, Any] | None, *, max_encoded_chars: int = 6_000_000) -> bytes:
    image = image_obj if isinstance(image_obj, dict) else {}
    raw = image.get("image_b64") or image.get("bytes_b64") or image.get("b64") or image.get("data_url")
    if not isinstance(raw, str) or not raw.strip() or len(raw) > max_encoded_chars:
        return b""
    value = raw.strip().split(",", 1)[1] if raw.startswith("data:") and "," in raw else raw.strip()
    try:
        return base64.b64decode(value.encode("utf-8"), validate=False)
    except Exception:
        return b""


def _merge_signals(images: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for image in images:
        signals = extract_image_cv_signals(image)
        for key in (
            "qr_code_detected", "qr_prompt_injection", "qr_external_url_detected",
            "ocr_prompt_injection", "manipulation_detected", "steg_suspicious",
            "ocr_low_confidence_uncertain",
        ):
            merged[key] = bool(merged.get(key) or signals.get(key))
        merged["adversarial_score"] = max(
            float(merged.get("adversarial_score") or 0.0),
            float(signals.get("adversarial_score") or 0.0),
        )
        for key in ("qr_payloads", "qr_payload_types"):
            values = [
                *list(merged.get(key) or []), *list(signals.get(key) or []),
            ]
            merged[key] = list(dict.fromkeys(str(value) for value in values if str(value)))[:12]
        if not merged.get("qr_redirect_probe") and signals.get("qr_redirect_probe"):
            merged["qr_redirect_probe"] = signals["qr_redirect_probe"]
    return merged


@dataclass(frozen=True)
class NormalizedChatImages:
    images: list[dict[str, Any]]
    labels: Any
    ocr_text: Any
    image_hash: Any
    intent: Any
    product_identity: Any
    cv_signals: dict[str, Any]
    damage_score: float
    is_product_photo: bool
    blob: bytes
    has_image: bool


def normalize_chat_images(payload: dict[str, Any] | None) -> NormalizedChatImages:
    source = payload if isinstance(payload, dict) else {}
    images = [row for row in list(source.get("images") or [])[:3] if isinstance(row, dict)]
    first = images[0] if images else {}
    labels = source.get("image_labels") or first.get("labels")
    ocr_text = source.get("image_ocr_text") or first.get("ocr_text")
    image_hash = source.get("image_hash") or first.get("image_hash") or first.get("hash")
    product_identity = source.get("image_product_identity") or extract_image_product_identity(first)
    blob = decode_image_b64(first) if images else decode_image_b64({"image_b64": source.get("image_b64")})
    if not image_hash and blob:
        image_hash = hashlib.sha256(blob).hexdigest()[:32]
    return NormalizedChatImages(
        images=images, labels=labels, ocr_text=ocr_text, image_hash=image_hash,
        intent=source.get("image_intent"), product_identity=product_identity,
        cv_signals=_merge_signals(images) if images else {},
        damage_score=float(first.get("damage_score") or 0.0),
        is_product_photo=bool(first.get("is_product_photo")), blob=blob,
        has_image=bool(labels or images),
    )


__all__ = [
    "NormalizedChatImages", "decode_image_b64", "extract_image_cv_signals",
    "extract_image_product_identity", "normalize_chat_images",
]
