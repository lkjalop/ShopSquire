"""Shipping-address validation (agnostic CORE).

There was NO address validation anywhere — checkout and plan-confirm accepted any string, so a
typo or a blank could produce an order that can never ship (and a dispatch that dead-letters at the
carrier). This is a format/plausibility gate: cheap deterministic checks now, PROVIDER-pluggable
(AusPost/Google) later behind a flag without touching the call sites.

Verdict severity, not a hard boolean, so checkout isn't brittle:
  * reject — unusable (empty / far too short / no locality-or-postcode signal): block.
  * warn   — plausible but weak (no recognizable postcode for the country): allow, flag on the order.
  * ok     — has the structural signals a shippable address needs.

Country postcode patterns are reference data (ISO code → regex), not product vocabulary. Pure;
never raises.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

# ISO country → postcode regex (reference data). Absent country → generic 3-10 alnum check.
_POSTCODE_PATTERNS: Dict[str, "re.Pattern"] = {
    "AU": re.compile(r"\b\d{4}\b"),
    "NZ": re.compile(r"\b\d{4}\b"),
    "US": re.compile(r"\b\d{5}(?:-\d{4})?\b"),
    "GB": re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.I),
    "CA": re.compile(r"\b[A-Z]\d[A-Z]\s*\d[A-Z]\d\b", re.I),
    "IN": re.compile(r"\b\d{6}\b"),
    "SG": re.compile(r"\b\d{6}\b"),
}
_GENERIC_POSTCODE = re.compile(r"\b[A-Z0-9]{3,10}\b", re.I)
_MIN_LEN = 8


def _has_locality_signal(text: str) -> bool:
    """A shippable address needs SOME structure beyond a single token — a comma/newline separator,
    or at least 3 whitespace-separated words (street + name + suburb)."""
    if "," in text or "\n" in text:
        return True
    return len(text.split()) >= 3


def validate_address(address: Optional[str], *, country: Optional[str] = None) -> Dict[str, Any]:
    """Validate a free-text shipping address. Returns
    {severity: ok|warn|reject, valid: bool, reason: str, country: str, has_postcode: bool}.
    Provider hook: ADDRESS_VALIDATION_PROVIDER (default 'none') — real verifiers wire here later."""
    raw = str(address or "").strip()
    cc = str(country or os.getenv("ADDRESS_DEFAULT_COUNTRY", "AU") or "AU").strip().upper()[:2]

    if not raw:
        return {"severity": "reject", "valid": False, "reason": "address_empty", "country": cc, "has_postcode": False}
    if len(raw) < _MIN_LEN:
        return {"severity": "reject", "valid": False, "reason": "address_too_short", "country": cc, "has_postcode": False}
    if not _has_locality_signal(raw):
        return {"severity": "reject", "valid": False, "reason": "no_locality_structure", "country": cc, "has_postcode": False}

    pat = _POSTCODE_PATTERNS.get(cc, _GENERIC_POSTCODE)
    has_postcode = bool(pat.search(raw))

    # Provider hook (future): a real verifier can upgrade/deny here; default is heuristic-only.
    provider = str(os.getenv("ADDRESS_VALIDATION_PROVIDER", "none")).strip().lower()
    if provider not in ("none", ""):
        # Real provider integration lands here (AusPost/Google). Until wired, fall through to
        # the heuristic verdict so enabling the flag never silently passes everything.
        pass

    if has_postcode:
        return {"severity": "ok", "valid": True, "reason": "ok", "country": cc, "has_postcode": True}
    return {"severity": "warn", "valid": True, "reason": "no_recognized_postcode",
            "country": cc, "has_postcode": False}
