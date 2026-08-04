"""Normalize buyer-stated procurement requirements before they become case state.

The language model may identify that a deadline exists, but consequential supplier
communication needs a bounded, unambiguous date.  This module accepts only ISO dates
or dates containing a named month; locale-ambiguous numeric dates are deliberately
left unresolved for clarification.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from dateutil import parser as date_parser


_MONTH = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?"
)
_DATE_PATTERNS = (
    re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b"),
    re.compile(rf"\b(\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH})\s+20\d{{2}})\b", re.I),
    re.compile(rf"\b((?:{_MONTH})\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,)?\s+20\d{{2}})\b", re.I),
)


def explicit_needed_by(text: str, *, today: Optional[date] = None) -> Optional[str]:
    """Return an ISO deadline only for an explicit, valid, non-past date."""
    raw = str(text or "")
    for pattern in _DATE_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        candidate = re.sub(r"(?<=\d)(?:st|nd|rd|th)\b", "", match.group(1), flags=re.I)
        try:
            parsed = date_parser.parse(candidate, fuzzy=False).date()
        except (TypeError, ValueError, OverflowError):
            continue
        if parsed < (today or date.today()):
            return None
        return parsed.isoformat()
    return None
