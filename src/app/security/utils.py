from __future__ import annotations

import re
from typing import Tuple


def normalize_digits(s: str) -> str:
    """Return only digit characters from string."""
    if not s:
        return ""
    return re.sub(r"[^0-9]", "", s)


def luhn_check(number: str) -> bool:
    """Perform Luhn algorithm check. Expects digits-only string."""
    if not number or not number.isdigit():
        return False
    total = 0
    reverse_digits = number[::-1]
    for i, ch in enumerate(reverse_digits):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def is_card_like(text: str) -> Tuple[bool, dict]:
    """Return (is_card_like, details) using length, luhn and nearby keywords.

    details includes: digits_len, luhn, keywords_found
    """
    if not text:
        return False, {}
    # Find candidate digit groups that look like PANs (allow spaces or hyphens between groups)
    candidates = []
    if text:
        # Match common spaced/hyphenated groupings (e.g. 4111-1111-1111-1111)
        for m in re.finditer(r'(?:\d[ \-]?){13,19}', text):
            cand = re.sub(r'[^0-9]', '', m.group(0))
            if 13 <= len(cand) <= 19:
                candidates.append(cand)
        # Also match contiguous digit runs as fallback
        for m in re.finditer(r'\d{13,19}', text):
            cand = m.group(0)
            if cand not in candidates:
                candidates.append(cand)
    # Choose the longest candidate if any
    cleaned = candidates[0] if candidates else normalize_digits(text)
    digits_len = len(cleaned)
    keywords = []
    low = text.lower()
    for kw in ("cvv", "expiry", "exp", "mm/yy", "visa", "mastercard", "amex", "card", "pan"):
        if kw in low:
            keywords.append(kw)
    luhn = False
    if 13 <= digits_len <= 19:
        luhn = luhn_check(cleaned)
    # Heuristic: require digit length and either luhn pass or payment keyword nearby
    is_card = (13 <= digits_len <= 19 and luhn) or (digits_len >= 13 and bool(keywords))
    return is_card, {"digits_len": digits_len, "luhn": luhn, "keywords": keywords}
