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


def contains_pci_data(text: str) -> bool:
    if not text:
        return False
    for m in CARD_RE.finditer(text):
        candidate = re.sub(r"[^0-9]", "", m.group(0))
        if 13 <= len(candidate) <= 19 and luhn_check(candidate):
            return True
    # CVV alone is not conclusive, but if combined with card-like sequences
    return bool(CVV_RE.search(text))
