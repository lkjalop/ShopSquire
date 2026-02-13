from __future__ import annotations

from typing import Dict, Any, Tuple
from src.app.deps import scrub_pii
from src.app.observability.metrics import record_control_failure
from src.app.security.pci import contains_pci_data


def redact_text(text: str) -> Tuple[str, bool, bool]:
    """Return redacted text and flags: (changed, pci_detected)."""
    try:
        pci = contains_pci_data(text or "")
    except Exception:
        pci = False
    redacted = scrub_pii(text or "")
    changed = redacted != (text or "")
    return redacted, changed, pci


def redact_payload(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int, bool]:
    """Redact strings in a nested payload; return (cleaned, changes_count, pci_detected)."""
    changes = 0
    pci_detected = False

    def _walk(v):
        nonlocal changes, pci_detected
        if isinstance(v, str):
            r, ch, pci = redact_text(v)
            if ch:
                changes += 1
            if pci:
                pci_detected = True
            return r
        if isinstance(v, dict):
            return {k: _walk(vv) for k, vv in v.items()}
        if isinstance(v, list):
            return [_walk(x) for x in v]
        return v

    cleaned = _walk(dict(payload or {}))
    if changes > 0:
        record_control_failure("GDPR-PII-Redaction")
    if pci_detected:
        record_control_failure("PCI-3.4")
    return cleaned, changes, pci_detected
