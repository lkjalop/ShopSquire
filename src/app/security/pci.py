import re

def luhn_check(number: str) -> bool:
    s = 0
    alt = False
    for ch in reversed(number):
        if not ch.isdigit():
            return False
        n = int(ch)
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        s += n
        alt = not alt
    return s % 10 == 0

CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
CVV_RE = re.compile(r"\b\d{3,4}\b")
CVV_HINT_RE = re.compile(r"\b(cvv|cvc|security code|card verification)\b", re.IGNORECASE)
CARD_HINT_RE = re.compile(r"\b(card|credit|debit|visa|mastercard|amex|american\s+express|discover)\b", re.IGNORECASE)
EXPIRY_RE = re.compile(r"\b(0[1-9]|1[0-2])\s*[/\-]\s*(\d{2}|\d{4})\b")


def contains_pci_data(text: str) -> bool:
    if not text:
        return False
    for m in CARD_RE.finditer(text):
        candidate = re.sub(r"[^0-9]", "", m.group(0))
        if 13 <= len(candidate) <= 19:
            # True PANs pass Luhn, but in demos/users often paste fake numbers.
            # If there's strong payment-card context (keywords/expiry), treat as PCI anyway.
            if luhn_check(candidate):
                return True
            if CARD_HINT_RE.search(text) or CVV_HINT_RE.search(text) or EXPIRY_RE.search(text):
                return True
    # CVV alone is not conclusive; require an explicit CVV/CVC hint
    if CVV_RE.search(text) and CVV_HINT_RE.search(text):
        return True
    return False
