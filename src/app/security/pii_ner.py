from __future__ import annotations

import re
from typing import Optional

from src.app.deps import scrub_pii

# Contextual lightweight NER fallback when spaCy is unavailable.
_NAME_CONTEXT_PAT = re.compile(
    r"(?i)\b(my name is|customer name|cardholder|recipient|ship to|billing name|ordered by|contact name|full name|account holder)\s*[:\-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})"
)
_ADDR_CONTEXT_PAT = re.compile(
    r"(?i)\b(address|street|ship to|billing address|delivery address|mailing address|home address|work address)\s*[:\-]?\s*([^\n,]{6,120})"
)
# Additional contextual patterns for free-text reasoning fields
_DOB_CONTEXT_PAT = re.compile(
    r"(?i)\b(date of birth|dob|birthday|born on)\s*[:\-]?\s*(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})"
)
_SSN_PAT = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PASSPORT_PAT = re.compile(r"(?i)\b(passport)\s*[:\-#]?\s*([A-Z0-9]{6,12})")
_DL_PAT = re.compile(r"(?i)\b(driver'?s?\s*licen[cs]e|DL)\s*[:\-#]?\s*([A-Z0-9]{5,15})")
_CREDIT_CARD_PAT = re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")
_IBAN_PAT = re.compile(r"\b[A-Z]{2}\d{2}\s?[A-Z0-9]{4}\s?(?:\d{4}\s?){2,7}\d{1,4}\b")
_ACCOUNT_NUM_PAT = re.compile(
    r"(?i)\b(account\s*(?:number|num|no|#))\s*[:\-]?\s*(\d{6,17})"
)


def redact_free_text_pii_ner(text: Optional[str]) -> str:
    """Best-effort NER-aware free-text PII redaction.

    Uses spaCy NER when installed; falls back to contextual regexes plus baseline
    scrub_pii redaction for emails/phones/IP/API keys.
    """
    raw = str(text or "")
    if not raw:
        return raw

    out = raw
    # Baseline deterministic redaction first.
    out = scrub_pii(out)

    # Optional NER pass.
    try:
        import spacy  # type: ignore

        model = None
        for name in ("en_core_web_sm", "en_core_web_md"):
            try:
                model = spacy.load(name)
                break
            except Exception:
                continue
        if model is not None:
            doc = model(out)
            redactions: list[tuple[int, int, str]] = []
            for ent in doc.ents:
                if ent.label_ in ("PERSON", "GPE", "LOC", "FAC", "ORG", "NORP", "ADDRESS"):
                    redactions.append((ent.start_char, ent.end_char, f"[REDACTED_{ent.label_}]"))
            if redactions:
                # Apply in reverse to preserve offsets.
                for s, e, r in sorted(redactions, key=lambda x: x[0], reverse=True):
                    out = out[:s] + r + out[e:]
    except Exception:
        pass

    # Contextual fallback catches common free-text segments even without spaCy.
    out = _NAME_CONTEXT_PAT.sub(lambda m: f"{m.group(1)} [REDACTED_PERSON]", out)
    out = _ADDR_CONTEXT_PAT.sub(lambda m: f"{m.group(1)} [REDACTED_ADDRESS]", out)
    out = _DOB_CONTEXT_PAT.sub(lambda m: f"{m.group(1)} [REDACTED_DOB]", out)
    out = _SSN_PAT.sub("[REDACTED_SSN]", out)
    out = _PASSPORT_PAT.sub(lambda m: f"{m.group(1)} [REDACTED_PASSPORT]", out)
    out = _DL_PAT.sub(lambda m: f"{m.group(1)} [REDACTED_DL]", out)
    out = _CREDIT_CARD_PAT.sub("[REDACTED_CC]", out)
    out = _IBAN_PAT.sub("[REDACTED_IBAN]", out)
    out = _ACCOUNT_NUM_PAT.sub(lambda m: f"{m.group(1)} [REDACTED_ACCOUNT]", out)
    return out
