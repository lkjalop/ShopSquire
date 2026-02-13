from typing import Dict, Any, Optional, List
import re

SERIAL_PATTERNS = {
    "electronics": {
        "apple": r"^[A-Z0-9]{12}$",
        "samsung": r"^R[A-Z0-9]{10}$",
    }
}

def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def extract_fields(text: str, patterns: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    t = normalize_text(text)
    fields: Dict[str, Any] = {}
    patterns = patterns or {}

    # Prefer vertical-pack patterns when provided
    order_pats = patterns.get("order_id") or [r"order\s*[:#-]?\s*([A-Z0-9-]{6,})"]
    serial_pats = patterns.get("serial") or [r"serial\s*[:#-]?\s*([A-Z0-9-]{4,})", r"s/?n\s*[:#-]?\s*([A-Z0-9-]{4,})"]

    for pat in order_pats:
        try:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                fields["order_id"] = m.group(1)
                break
        except re.error:
            continue

    for pat in serial_pats:
        try:
            m2 = re.search(pat, t, re.IGNORECASE)
            if m2:
                fields["serial"] = m2.group(1)
                break
        except re.error:
            continue
    return fields

def serial_mismatch(expected: Optional[str], observed: Optional[str]) -> bool:
    if not expected or not observed:
        return False
    return normalize_text(expected) != normalize_text(observed)

