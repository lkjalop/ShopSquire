from __future__ import annotations

from typing import Any, Dict, Iterable
import hashlib

from src.app.deps import security_sanitize, redact_for_trace


def sanitize_event_payload(event: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize and redact an event payload for external emission.

    Applies unicode normalization, PII scrubbing, and redaction of large/blobby fields.
    """
    try:
        # First scrub PII and normalize
        sanitized = security_sanitize(event or {})
        # Then redact bulky/base64-like fields
        redacted = redact_for_trace(sanitized)
        return redacted if isinstance(redacted, dict) else {}
    except Exception:
        return {}


def hash_fields(event: Dict[str, Any], fields: Iterable[str]) -> Dict[str, Any]:
    """Return a shallow copy of event with selected fields replaced by SHA-256 short hashes.

    Useful for `resource_id`, `email`, etc. Only hashes string values.
    """
    out = dict(event or {})
    for f in fields:
        try:
            v = out.get(f)
            if isinstance(v, str) and v:
                hv = hashlib.sha256(v.encode("utf-8")).hexdigest()[:16]
                out[f] = hv
        except Exception:
            continue
    return out
