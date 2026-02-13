from __future__ import annotations

from typing import Dict, Optional


def _get(h: Dict[str, str], key: str) -> Optional[str]:
    for k, v in h.items():
        if k.lower() == key.lower():
            return v
    return None


def validate_email_auth(headers: Dict[str, str]) -> Dict[str, str | bool | None]:
    """Parse common auth results from email headers (best-effort).

    Looks for Authentication-Results, DKIM-Signature, and Received-SPF.
    Returns flags indicating pass/fail/unknown for SPF/DKIM/DMARC.
    """
    auth_results = _get(headers, "Authentication-Results") or ""
    dkim_sig = _get(headers, "DKIM-Signature")
    spf = _get(headers, "Received-SPF") or ""

    spf_pass = ("pass" in spf.lower()) or ("spf=pass" in auth_results.lower())
    dkim_pass = (dkim_sig is not None) and ("dkim=pass" in auth_results.lower())
    dmarc_pass = ("dmarc=pass" in auth_results.lower())

    return {
        "spf_pass": bool(spf_pass),
        "dkim_pass": bool(dkim_pass),
        "dmarc_pass": bool(dmarc_pass),
        "authentication_results": auth_results or None,
    }


def detect_bec_indicators(text: str, from_domain: Optional[str] = None) -> Dict[str, bool]:
    """Heuristics to flag Business Email Compromise indicators in message text.

    Flags urgency, wire/gift-card requests, bank detail changes, and domain lookalikes.
    """
    import re
    t = (text or "").lower()
    indicators = {
        "urgency": any(w in t for w in ["urgent", "immediately", "asap", "today"]),
        "wire_transfer": any(w in t for w in ["wire", "bank transfer", "iban", "swift"]),
        "gift_cards": any(w in t for w in ["gift card", "itunes", "amazon cards", "codes"]),
        "change_bank_details": any(w in t for w in ["change bank", "update account", "new account"]),
    }
    # Simple lookalike domain heuristic (typosquatting: rn vs m, 0 vs o)
    if from_domain:
        suspicious = False
        try:
            clean = from_domain.lower().strip()
            suspicious = bool(re.search(r"(rn|vv|l1|0o)", clean))
        except Exception:
            suspicious = False
        indicators["lookalike_domain"] = suspicious
    else:
        indicators["lookalike_domain"] = False
    return indicators
