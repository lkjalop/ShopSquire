"""Collect normalized email addresses from structured incident evidence."""
import re
from typing import Any, List

_EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def extract_emails(value: Any) -> List[str]:
    out: List[str] = []
    if value is None:
        return out
    if isinstance(value, list):
        for x in value:
            out.extend(extract_emails(x))
        return out
    if isinstance(value, dict):
        for x in value.values():
            out.extend(extract_emails(x))
        return out
    text = str(value or "").strip()
    if not text:
        return out
    return [m.group(0).lower() for m in _EMAIL_RE.finditer(text)]
