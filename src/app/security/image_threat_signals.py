from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from typing import Any, Dict, List

PROMPT_INJECTION_PAT = re.compile(
    r"(?i)(ignore\s+previous|override\s+instructions|system\s*prompt|developer\s*mode|"
    r"jailbreak|do\s+not\s+follow|bypass\s+policy|exfiltrate|export\s+all|"
    r"show\s+secret|tool\s*:|function\s*call|execute\s+shell)"
)
PAYMENT_SE_PAT = re.compile(
    r"(?i)\b(pay[\W_]*(?:id|1d|ld)|bsb|iban|swift|venmo|cashapp|zelle|wallet|transfer|send\s+money)\b"
)
CRYPTO_URI_PAT = re.compile(r"(?i)\b(bitcoin:|ethereum:|monero:|litecoin:)\b")
RANSOM_PAT = re.compile(
    r"(?i)\b(encrypted|ransom|decrypt|pay\s+within|restore\s+files|btc\s+wallet|files\s+locked)\b"
)
PCI_PAT = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
PCI_EXPIRY_PAT = re.compile(r"\b(?:0[1-9]|1[0-2])\s*/\s*(?:\d{2}|\d{4})\b")
PCI_CVV_PAT = re.compile(r"\b(?:cvv|cvc|security\s*code)\b", re.I)
B64_PAT = re.compile(r"\b(?:[A-Za-z0-9+/]{24,}={0,2})\b")
HEX_PAT = re.compile(r"\b(?:0x)?[0-9a-fA-F]{24,}\b")
AGENTIC_PAT = re.compile(
    r"(?is)(\"tool\"\s*:|\"function\"\s*:|\"name\"\s*:|tool_call|function_call|"
    r"add_to_cart|remove_from_cart|checkout|place_order|cancel_order|refund_order|"
    r"execute_shell|run_command|curl\s+https?://|wget\s+https?://)"
)
SPLIT_INJECTION_COMPOSITE_PAT = re.compile(
    r"(?is)(ignore\s+previous.*instructions|system\s*prompt|developer\s*mode|"
    r"tool\s*:|function\s*call|add_to_cart|checkout|place_order)"
)
LABEL_HINT_PAT = re.compile(
    r"(?i)\b(warranty|official|support|repair|return|invoice|receipt|university|student|gaming|office)\b"
)


def detect_ocr_prompt_injection(text: str | None) -> bool:
    if not text:
        return False
    return bool(PROMPT_INJECTION_PAT.search(text))


def luhn_ok(num: str) -> bool:
    digits = [int(c) for c in re.sub(r"\D", "", num)]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for i, d in enumerate(digits):
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def sanitize_unicode_injection(text: str | None) -> str:
    t = unicodedata.normalize("NFKC", str(text or ""))
    # Newlines and tabs are ordinary document layout, not obfuscation. Removing
    # them made every multi-line OCR/PDF/TXT payload look like a homoglyph attack.
    return "".join(
        ch for ch in t
        if unicodedata.category(ch) != "Cf"
        and (unicodedata.category(ch) != "Cc" or ch in {"\n", "\r", "\t"})
    )


def detect_ocr_encoded_payload(text: str | None) -> Dict[str, Any]:
    t = str(text or "")
    if not t.strip():
        return {"detected": False, "decoded_preview": "", "kind": None}
    for token in B64_PAT.findall(t):
        try:
            raw = base64.b64decode(token, validate=True)
            dec = raw.decode("utf-8", errors="ignore").strip()
            if dec and len(dec) >= 8:
                return {"detected": True, "decoded_preview": dec[:160], "kind": "base64"}
        except (ValueError, binascii.Error):
            continue
        except Exception:
            continue
    for token in HEX_PAT.findall(t):
        s = token[2:] if token.lower().startswith("0x") else token
        if len(s) % 2 != 0:
            continue
        try:
            dec = bytes.fromhex(s).decode("utf-8", errors="ignore").strip()
            if dec and len(dec) >= 8:
                return {"detected": True, "decoded_preview": dec[:160], "kind": "hex"}
        except Exception:
            continue
    return {"detected": False, "decoded_preview": "", "kind": None}


def normalize_ocr_and_detect(text: str | None) -> Dict[str, Any]:
    raw = str(text or "")
    normalized = sanitize_unicode_injection(raw)
    encoded = detect_ocr_encoded_payload(normalized)
    decoded_preview = str(encoded.get("decoded_preview") or "")
    detection_text = f"{normalized} {decoded_preview}".strip()
    card_hits = [m.group(0) for m in PCI_PAT.finditer(detection_text)]
    pci_hits = [x for x in card_hits if luhn_ok(x)]
    # OCR can corrupt single digits; keep a suspicious PCI signal when card-like
    # sequences appear with payment context (expiry/CVV/payment language).
    payment_context = bool(PAYMENT_SE_PAT.search(detection_text))
    expiry_context = bool(PCI_EXPIRY_PAT.search(detection_text))
    cvv_context = bool(PCI_CVV_PAT.search(detection_text))
    card_like_context = bool(card_hits and (payment_context or expiry_context or cvv_context))
    pci_exposed = bool(pci_hits) or card_like_context
    return {
        "raw_text": raw,
        "normalized_text": normalized,
        "encoded_payload_detected": bool(encoded.get("detected")),
        "encoded_payload_kind": encoded.get("kind"),
        "encoded_preview": decoded_preview,
        "payment_social_engineering": bool(PAYMENT_SE_PAT.search(detection_text)),
        "pci_card_exposed": pci_exposed,
        "pci_match_count": len(pci_hits),
        "pci_card_like_count": len(card_hits),
        "crypto_payment_uri": bool(CRYPTO_URI_PAT.search(detection_text)),
        "ransomware_indicator": bool(RANSOM_PAT.search(detection_text)),
        "homoglyph_injection": normalized != raw,
        "agentic_tool_injection": bool(AGENTIC_PAT.search(detection_text)),
    }


def detect_cross_image_split_injection(texts: List[str]) -> bool:
    chunks = [str(t or "").strip() for t in (texts or []) if str(t or "").strip()]
    if len(chunks) < 2:
        return False
    if any(detect_ocr_prompt_injection(t) for t in chunks):
        return False
    joined = " ".join(chunks)
    return bool(SPLIT_INJECTION_COMPOSITE_PAT.search(joined))


def detect_qr_label_destination_mismatch(
    qr_codes: List[Dict[str, Any]] | None,
    *,
    image_consistency: Dict[str, Any] | None = None,
) -> bool:
    codes = [c for c in (qr_codes or []) if isinstance(c, dict)]
    if not codes:
        return False
    by_file_ocr: Dict[str, str] = {}
    try:
        for im in ((image_consistency or {}).get("images") or []):
            if not isinstance(im, dict):
                continue
            fn = str(im.get("filename") or "").strip()
            if not fn:
                continue
            by_file_ocr[fn] = str(im.get("ocr_text") or "").strip()
    except Exception:
        by_file_ocr = {}
    payload_types = {str(c.get("payload_type") or "").strip().lower() for c in codes}
    payload_types.discard("")
    if len(payload_types) > 1:
        bbox_count = 0
        for c in codes:
            bb = c.get("bbox") if isinstance(c.get("bbox"), dict) else None
            if bb and any(bb.get(k) is not None for k in ("left", "top", "width", "height")):
                bbox_count += 1
        if bbox_count >= 2:
            return True
    for c in codes:
        ptype = str(c.get("payload_type") or "").strip().lower()
        data = str(c.get("data") or "").strip()
        fn = str(c.get("filename") or "").strip()
        ocr_text = by_file_ocr.get(fn, "")
        has_human_label = bool(LABEL_HINT_PAT.search(ocr_text))
        if ptype == "url" and data.lower().startswith(("http://", "https://")) and has_human_label:
            return True
        if ptype in {"wifi_credentials", "crypto_uri"} and has_human_label:
            return True
    return False
