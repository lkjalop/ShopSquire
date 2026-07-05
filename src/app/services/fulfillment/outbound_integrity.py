"""Outbound supplier-message integrity guard (agnostic CORE).

THE THREAT: the platform DRAFTS RFQ/PO emails to suppliers from bulk-order data (product names,
quantities, buyer notes). If any of that content is poisoned — a phishing link hidden in a product
name, injected instructions, an exfil/C2 string, or a leaked secret/PII — and we send it, WE become
the attacker's delivery vector into a trusted supplier's inbox. Destination allowlisting + GATE-2
already stop sending to the WRONG place; this stops sending the WRONG CONTENT to the right place.

Scans the DRAFTED subject+body right before it leaves, on every supplier send seam, for:
  * data LEAVING     — secrets (block) / PII (flag), reusing the outbound content-DLP patterns;
  * payloads we'd RELAY — external links, prompt-injection, exfil/C2, dangerous-tool strings, QR refs
    (a legitimate machine-drafted RFQ has NONE of these — their presence means poisoned input).

Verdict: block / review / allow. Pure regex over the text; never raises. Vertical-blind.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

# A machine-drafted RFQ never legitimately contains these — their presence means buyer/product
# input carried a payload we'd be relaying to a supplier. Reuse the inbound rule intent.
_URL_RE = re.compile(r"https?://[^\s<>()\"']+", re.I)
_PROMPT_INJECTION_RE = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|prompts?)|"
    r"disregard\s+(?:the\s+)?(?:instructions?|rules?|system)|you\s+are\s+now\s+|"
    r"system\s*:\s*|assistant\s*:\s*|<\|im_start\|>|new\s+instructions?:)"
)
_EXFIL_C2_RE = re.compile(
    r"(?i)(exfiltrate|dump\s+(?:the\s+)?database|export\s+all\s+(?:customers?|data)|"
    r"steal\s+credentials?|base64\s*-?d|curl\s+https?://|wget\s+https?://|"
    r"invoke-expression|iex\s*\(|powershell\s+-enc)"
)
_QR_HINT_RE = re.compile(r"(?i)(scan\s+(?:the\s+)?qr|qr\s*code|\bdata:image/)")

# SENSITIVE-data leak patterns for the SUPPLIER path specifically. A supplier RFQ LEGITIMATELY
# carries dates (delivery deadlines), a ship-to address, quantities, and the supplier's own
# contact — so the broad buyer-facing PII scan (which flags dates as DOB, addresses, names)
# over-triggers here. We flag only what must NEVER reach a supplier: payment cards + government
# identity numbers. Secrets/credentials are handled separately (dlp_scrub_text) and hard-block.
_PAN_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")           # 13-19 digit card
_TFN_RE = re.compile(r"\b[1-9]\d{2}[ \-]\d{3}[ \-]\d{3}\b")           # AU Tax File Number
_MEDICARE_RE = re.compile(r"\b[2-6]\d{3}[ \-]?\d{5}[ \-]?\d{1,2}\b")  # AU Medicare


def _sensitive_pii_hits(blob: str) -> int:
    hits = 0
    for pat in (_PAN_RE, _TFN_RE, _MEDICARE_RE):
        if pat.search(blob):
            hits += 1
    return hits


def scan_outbound_supplier_message(subject: str, body: str, *, recipient: str = "") -> Dict[str, Any]:
    """Integrity verdict for one drafted supplier message. Returns
    {action: block|review|allow, findings:[...], categories:[...], dlp:{...}}. Never raises."""
    subj = str(subject or "")
    bod = str(body or "")
    blob = f"{subj}\n{bod}"
    findings: List[str] = []
    categories: List[str] = []

    # 1) Data leaving — SECRETS hard-block; only high-sensitivity PII (cards / identity numbers)
    # flags, since a legitimate RFQ carries dates + a ship-to address the broad PII scan mis-flags.
    secret_hits = 0
    try:
        from src.app.security.dlp_export import dlp_scrub_text
        _, secret_hits = dlp_scrub_text(blob)
    except Exception:
        secret_hits = 0
    sensitive_pii = _sensitive_pii_hits(blob)
    dlp = {"secret_hits": int(secret_hits), "sensitive_pii_hits": int(sensitive_pii),
           "action": ("block" if secret_hits else ("review" if sensitive_pii else "allow"))}
    if secret_hits:
        findings.append("secret_in_outbound_body")
        categories.append("data_leak")
    elif sensitive_pii:
        findings.append("sensitive_pii_in_outbound_body")
        categories.append("data_leak")

    # 2) Payloads we would RELAY — none of these belong in a machine-drafted RFQ.
    relay_block = False
    if _PROMPT_INJECTION_RE.search(blob):
        findings.append("relayed_prompt_injection"); categories.append("relay_payload"); relay_block = True
    if _EXFIL_C2_RE.search(blob):
        findings.append("relayed_exfil_or_c2"); categories.append("relay_payload"); relay_block = True
    if _URL_RE.search(blob):
        # An external link in an RFQ is anomalous (we don't send suppliers links) → review, not block.
        findings.append("relayed_external_link"); categories.append("relay_link")
    if _QR_HINT_RE.search(blob):
        findings.append("relayed_qr_reference"); categories.append("relay_link")

    # Decide: any secret leaving OR any injected executable payload → BLOCK; links/sensitive-PII/QR → REVIEW.
    if secret_hits or relay_block:
        action = "block"
    elif findings:
        action = "review"
    else:
        action = "allow"
    return {"action": action, "findings": sorted(set(findings)),
            "categories": sorted(set(categories)), "dlp": dlp}
