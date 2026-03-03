from __future__ import annotations

import re
from typing import Dict, Optional


def _get(h: Dict[str, str], key: str) -> Optional[str]:
    for k, v in h.items():
        if k.lower() == key.lower():
            return v
    return None


_AR_TOKEN_RE = re.compile(r"(?i)\b([a-z0-9_-]+)\s*=\s*([a-z0-9_-]+)")
_ARC_CV_RE = re.compile(r"(?i)\bcv\s*=\s*(none|pass|fail)\b")


def _parse_auth_results(raw: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in _AR_TOKEN_RE.finditer(str(raw or "")):
        k = str(m.group(1) or "").strip().lower()
        v = str(m.group(2) or "").strip().lower()
        if k and v:
            out[k] = v
    return out


def validate_email_auth(headers: Dict[str, str]) -> Dict[str, str | bool | None]:
    """Parse common auth results from email headers (best-effort).

    Looks for Authentication-Results, DKIM-Signature, Received-SPF, ARC and BIMI.
    Returns flags indicating pass/fail/unknown for SPF/DKIM/DMARC and ARC/BIMI hints.
    """
    auth_results = _get(headers, "Authentication-Results") or ""
    parsed_ar = _parse_auth_results(auth_results)
    dkim_sig = _get(headers, "DKIM-Signature")
    spf = _get(headers, "Received-SPF") or ""
    arc_auth_results = _get(headers, "ARC-Authentication-Results") or ""
    arc_seal = _get(headers, "ARC-Seal") or ""
    arc_msg_sig = _get(headers, "ARC-Message-Signature") or ""
    bimi_location = _get(headers, "BIMI-Location")
    bimi_indicator = _get(headers, "BIMI-Indicator")

    spf_res = str(parsed_ar.get("spf") or "").lower()
    dkim_res = str(parsed_ar.get("dkim") or "").lower()
    dmarc_res = str(parsed_ar.get("dmarc") or "").lower()
    bimi_res = str(parsed_ar.get("bimi") or "").lower()

    spf_pass = ("pass" in spf.lower()) or (spf_res == "pass")
    dkim_pass = (dkim_sig is not None and dkim_sig.strip() != "") and (dkim_res == "pass" or "dkim=pass" in auth_results.lower())
    dmarc_pass = (dmarc_res == "pass") or ("dmarc=pass" in auth_results.lower())

    arc_present = bool((arc_auth_results or "").strip() or (arc_seal or "").strip() or (arc_msg_sig or "").strip())
    arc_cv_match = _ARC_CV_RE.search(arc_seal or "")
    arc_cv = str(arc_cv_match.group(1)).lower() if arc_cv_match else None
    arc_chain_valid: bool | None = None
    if arc_cv == "pass":
        arc_chain_valid = True
    elif arc_cv == "fail":
        arc_chain_valid = False

    bimi_present = bool((bimi_location or "").strip() or (bimi_indicator or "").strip() or bimi_res)
    bimi_pass = bimi_res == "pass"
    bimi_fail = bimi_res in ("fail", "temperror", "permerror")

    return {
        "spf_pass": bool(spf_pass),
        "dkim_pass": bool(dkim_pass),
        "dmarc_pass": bool(dmarc_pass),
        "spf_result": spf_res or None,
        "dkim_result": dkim_res or None,
        "dmarc_result": dmarc_res or None,
        "authentication_results": auth_results or None,
        "arc_present": arc_present,
        "arc_cv": arc_cv,
        "arc_chain_valid": arc_chain_valid,
        "arc_fail": bool(arc_cv == "fail"),
        "bimi_present": bimi_present,
        "bimi_result": bimi_res or None,
        "bimi_pass": bimi_pass,
        "bimi_fail": bimi_fail,
        "bimi_location": (str(bimi_location).strip()[:2048] if bimi_location else None),
        "bimi_indicator": (str(bimi_indicator).strip()[:2048] if bimi_indicator else None),
    }


def detect_bec_indicators(
    text: str,
    from_domain: Optional[str] = None,
    *,
    from_address: Optional[str] = None,
    display_name: Optional[str] = None,
    known_domains: Optional[list[str]] = None,
) -> Dict[str, bool | float]:
    """Enhanced BEC detection with semantic urgency, Levenshtein domain similarity,
    homoglyph detection, CEO impersonation patterns, and invoice redirect signals.

    Returns indicator flags plus a composite ``bec_risk_score`` (0.0–1.0).
    """
    import re
    t = (text or "").lower()

    # --- Semantic urgency (weighted keyword categories) ---
    _URGENCY_STRONG = ["urgent", "immediately", "right now", "asap", "time sensitive"]
    _URGENCY_MEDIUM = ["today", "by end of day", "quickly", "as soon as possible", "deadline"]
    _URGENCY_WEAK = ["soon", "promptly", "at your earliest"]
    urgency_score = 0.0
    for w in _URGENCY_STRONG:
        if w in t:
            urgency_score = max(urgency_score, 1.0)
    for w in _URGENCY_MEDIUM:
        if w in t:
            urgency_score = max(urgency_score, 0.6)
    for w in _URGENCY_WEAK:
        if w in t:
            urgency_score = max(urgency_score, 0.3)

    # --- Action indicators ---
    wire_transfer = any(w in t for w in ["wire", "bank transfer", "iban", "swift", "routing number", "ach"])
    gift_cards = any(w in t for w in ["gift card", "itunes", "amazon cards", "codes", "prepaid card", "google play"])
    change_bank = any(w in t for w in ["change bank", "update account", "new account", "new banking", "updated payment"])
    invoice_redirect = any(w in t for w in [
        "updated invoice", "revised invoice", "new payment details",
        "please use this account", "send payment to", "pay to the following",
    ])

    # --- CEO impersonation detection ---
    _EXEC_TITLES = ["ceo", "cfo", "cto", "coo", "president", "director", "vice president", "vp"]
    ceo_impersonation = False
    dn = (display_name or "").lower()
    if dn:
        ceo_impersonation = any(title in dn for title in _EXEC_TITLES)
    if not ceo_impersonation:
        # Check body for impersonation: "I'm the CEO", "Sent from my iPhone — John, CEO"
        ceo_impersonation = bool(re.search(r"\b(?:i(?:'m| am) (?:the )?(?:ceo|cfo|cto|president))\b", t))

    # --- Homoglyph detection (Unicode confusables) ---
    _HOMOGLYPHS = {
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p",
        "\u0441": "c", "\u0443": "y", "\u0445": "x", "\u04bb": "h",
        "\u0456": "i", "\u0455": "s", "\u2018": "'", "\u2019": "'",
    }
    homoglyph_detected = False
    if from_domain:
        for char in from_domain:
            if char in _HOMOGLYPHS:
                homoglyph_detected = True
                break

    # --- Levenshtein domain similarity ---
    lookalike_domain = False
    domain_similarity: float = 0.0
    if from_domain and known_domains:
        clean = from_domain.lower().strip()
        for legit in known_domains:
            sim = _levenshtein_similarity(clean, legit.lower().strip())
            domain_similarity = max(domain_similarity, sim)
            if 0.75 <= sim < 1.0:
                lookalike_domain = True
    elif from_domain:
        # Fall back to regex heuristic
        try:
            clean = from_domain.lower().strip()
            lookalike_domain = bool(re.search(r"(rn|vv|l1|0o)", clean))
        except Exception:
            pass

    # --- Composite BEC risk score ---
    score = 0.0
    score += urgency_score * 0.15
    score += (0.20 if wire_transfer else 0.0)
    score += (0.15 if gift_cards else 0.0)
    score += (0.15 if change_bank else 0.0)
    score += (0.10 if invoice_redirect else 0.0)
    score += (0.10 if ceo_impersonation else 0.0)
    score += (0.10 if lookalike_domain or homoglyph_detected else 0.0)
    score += min(domain_similarity * 0.05, 0.05) if domain_similarity >= 0.75 else 0.0
    score = min(score, 1.0)

    return {
        "urgency": urgency_score >= 0.6,
        "urgency_score": urgency_score,
        "wire_transfer": wire_transfer,
        "gift_cards": gift_cards,
        "change_bank_details": change_bank,
        "invoice_redirect": invoice_redirect,
        "ceo_impersonation": ceo_impersonation,
        "homoglyph_detected": homoglyph_detected,
        "lookalike_domain": lookalike_domain,
        "domain_similarity": domain_similarity,
        "bec_risk_score": round(score, 3),
    }


def _levenshtein_similarity(a: str, b: str) -> float:
    """Compute normalized Levenshtein similarity between two strings (0.0–1.0)."""
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    # Standard DP Levenshtein distance
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    dist = prev[lb]
    return 1.0 - dist / max(la, lb)


# ---------------------------------------------------------------------------
# Thread hijacking detection
# ---------------------------------------------------------------------------
def detect_thread_hijack(
    headers: Dict[str, str],
    *,
    known_thread_domains: Optional[set[str]] = None,
) -> Dict[str, bool | str | None]:
    """Detect thread hijacking: an inbound email referencing an existing thread
    but originating from a different/unknown domain.

    Also flags lateral-movement indicators: internal config URLs, credentials,
    or API keys appearing in forwarded content.
    """
    from_addr = _get(headers, "From") or ""
    references = _get(headers, "References") or ""
    in_reply_to = _get(headers, "In-Reply-To") or ""
    subject = _get(headers, "Subject") or ""

    is_reply = bool(in_reply_to.strip() or references.strip())
    # Extract domain from From header
    from_domain = None
    if "@" in from_addr:
        from_domain = from_addr.rsplit("@", 1)[-1].strip().lower().rstrip(">")

    # Extract domains from References / In-Reply-To message-IDs
    ref_domains: set[str] = set()
    for mid in re.findall(r"<[^>]+@([^>]+)>", references + " " + in_reply_to):
        ref_domains.add(mid.strip().lower())

    thread_hijack = False
    if is_reply and from_domain and ref_domains:
        # If the sending domain is NOT in any of the referenced message-ID domains
        if from_domain not in ref_domains:
            thread_hijack = True
        # If known_thread_domains provided, check against that too
        if known_thread_domains and from_domain not in known_thread_domains:
            thread_hijack = True

    # Lateral movement indicators in subject/body-like headers
    forwarded_content = (_get(headers, "X-Forwarded-Message") or "") + " " + subject
    _LATERAL_PATTERNS = [
        r"(?:password|passwd|pwd)\s*[:=]\s*\S+",
        r"(?:api[_-]?key|token|secret)\s*[:=]\s*\S+",
        r"https?://(?:10\.\d+|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+",
        r"(?:mongodb|postgres|mysql|redis)://\S+",
    ]
    lateral_movement = False
    fc_lower = forwarded_content.lower()
    for pat in _LATERAL_PATTERNS:
        if re.search(pat, fc_lower):
            lateral_movement = True
            break

    return {
        "is_reply": is_reply,
        "thread_hijack": thread_hijack,
        "from_domain": from_domain,
        "ref_domains": sorted(ref_domains) if ref_domains else [],
        "lateral_movement": lateral_movement,
    }
