from __future__ import annotations

import re
import idna
import hashlib
import unicodedata
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, List, Tuple

from src.app.config import load_feature_flags, get_settings
from src.app.rules.tenant_config_store import TenantConfigStore


KNOWN_BRANDS = [
    "microsoft.com",
    "amazon.com",
    "paypal.com",
    "shopify.com",
    "google.com",
]

_PROMPT_INJECTION_PAT = re.compile(
    r"(?i)(ignore\s+previous|system\s*prompt|developer\s*mode|jailbreak|"
    r"bypass\s+policy|tool\s*:|function\s*call|execute\s+shell|exfiltrate)"
)

_DANGEROUS_TOOL_PAT = re.compile(
    r"(?i)(run\s+shell|execute\s+command|download\s+and\s+run|dump\s+database|"
    r"export\s+all\s+customers|read\s+secrets|rotate\s+keys\s+without\s+approval)"
)

_BANK_CHANGE_PAT = re.compile(
    r"(?i)(update\s+bank|new\s+bank\s+account|change\s+payment\s+details|"
    r"changing\s+payment\s+procedures|updated\s+payment\s+details|"
    r"bank(?:ing)?\s+details\s+(?:have\s+)?recently\s+changed|"
    r"disregard\s+(?:any\s+)?previous\s+remittance\s+instructions|"
    r"wire\s+to\s+new\s+account|remit\s+to\s+new\s+beneficiary|"
    r"updated\s+beneficiary\s+account)"
)

_INVOICE_REDIRECT_PAT = re.compile(r"(?i)(invoice\s+redirect|send\s+payment\s+to|new\s+remittance)")
_URGENCY_PAT = re.compile(r"(?i)(urgent|asap|immediately|today\s+only|confidential)")
_CANARY_PAT = re.compile(r"(?i)(canarytoken|canary\\.tokens|x-canary-id|__canary__)")
_LOLBINS_PAT = re.compile(
    r"(?i)\b(certutil|mshta|rundll32|bitsadmin|regsvr32|powershell\s+-enc(?:odedcommand)?|powershell\s+/enc)\b"
)
_RANSOMWARE_PAT = re.compile(
    r"(?i)(ransomware|your\s+files\s+(are|were)\s+encrypted|decrypt(?:ion)?\s+key|bitcoin\s+payment|"
    r"pay\s+within\s+\d+\s*(?:hours?|days?)|data\s+will\s+be\s+leaked)"
)
_EXFIL_PAT = re.compile(
    r"(?i)(data\s+exfiltration|exfiltrate|export\s+all\s+customers|dump\s+database|steal\s+credentials|"
    r"upload\s+(?:to|into)\s+(?:mega|dropbox|gdrive|google\s*drive|onedrive)|bulk\s+download\s+records)"
)
_KEYLOGGER_PAT = re.compile(
    r"(?i)(keylogger|keystroke\s+logger|credential\s+harvester|form\s+grabber|capture\s+passwords?)"
)
_C2_BEACON_PAT = re.compile(
    r"(?i)(c2|command\s+and\s+control|beacon(?:ing)?|callback\s+server|connect-back|polling\s+interval)"
)
_FILELESS_PAT = re.compile(
    r"(?i)(invoke-expression|iex\s*\(|powershell\s+-w\s+hidden|regsvr32\s+.*https?://|"
    r"mshta\s+https?://|rundll32\s+javascript:|wmic\s+process\s+call\s+create)"
)
_URL_SHORTENER_DOMAINS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "rb.gy", "ow.ly", "is.gd"}
_OCR_OVERLAY_PAYMENT_PAT = re.compile(
    r"(?i)(payid|scan\s*(the)?\s*qr|qr\s*code|pay\s+to|send\s+payment|"
    r"bank\s+transfer|remit\s+to|beneficiary|account\s+number|bsb|swift)"
)
_OCR_OVERLAY_BENIGN_CATALOG_PAT = re.compile(
    r"(?i)(sku|model|spec(?:ification)?s?|warranty|catalog(?:ue)?|"
    r"resolution|inch|ram|ssd|cpu|battery|price|rrp)"
)


def _get_thresholds(*, tenant_id: str | None = None) -> Dict[str, Any]:
    try:
        thr = (load_feature_flags(get_settings().feature_flags_path) or {}).get("SECURITY_THRESHOLDS", {})
    except Exception:
        thr = {}
    # Optional tenant-scoped override for allow/deny lists via TenantConfigStore.
    # Config key: email_security_ioc_lists
    try:
        if tenant_id:
            override = TenantConfigStore(cache_ttl=10).get_override("email_security_ioc_lists", tenant_id=tenant_id) or {}
            if isinstance(override, dict):
                thr = dict(thr or {})
                for k in ("DOMAIN_DENYLIST", "DOMAIN_ALLOWLIST", "IP_DENYLIST", "IP_ALLOWLIST"):
                    if k in override:
                        thr[k] = override.get(k)
    except Exception:
        pass
    return thr


def normalize_domain(domain: str | None) -> str | None:
    if not domain:
        return None
    try:
        # Decode punycode / IDN
        raw = unicodedata.normalize("NFKC", domain.strip().lower())
        if raw.startswith("xn--") or ".xn--" in raw:
            return idna.decode(raw)
        return raw
    except Exception:
        try:
            return unicodedata.normalize("NFKC", domain.strip().lower())
        except Exception:
            return domain.strip().lower()


def extract_domain(addr: str | None) -> str | None:
    if not addr:
        return None
    try:
        from email.utils import parseaddr

        candidate = str(parseaddr(addr)[1] or "").strip()
        if not candidate:
            candidate = str(addr or "").strip()
        if "<" in candidate and ">" in candidate:
            m2 = re.search(r"<([^>]+)>", candidate)
            if m2:
                candidate = m2.group(1).strip()
        if "@" not in candidate:
            m = re.search(r"@([^\s>;,]+)", candidate)
            return normalize_domain(m.group(1) if m else None)
        dom = candidate.rsplit("@", 1)[-1].strip().strip(">").strip()
        dom = dom.rstrip(".,;:")
        return normalize_domain(dom or None)
    except Exception:
        return None


def _confusable_skeleton(text: str | None) -> str:
    if not text:
        return ""
    conf_map = {
        "\u0430": "a", "\u0435": "e", "\u043e": "o", "\u0440": "p", "\u0441": "c", "\u0443": "y", "\u0445": "x",
        "\u0456": "i", "\u0458": "j", "\u04cf": "l", "\u0501": "d", "\u04bb": "h", "\u0578": "n",
        "\u0391": "A", "\u0392": "B", "\u0395": "E", "\u0396": "Z", "\u0397": "H", "\u0399": "I", "\u039a": "K",
        "\u039c": "M", "\u039d": "N", "\u039f": "O", "\u03a1": "P", "\u03a4": "T", "\u03a5": "Y", "\u03a7": "X",
    }
    norm = unicodedata.normalize("NFKC", str(text).lower())
    return "".join(conf_map.get(ch, ch) for ch in norm)


def _has_non_ascii(text: str | None) -> bool:
    if not text:
        return False
    try:
        return any(ord(ch) > 127 for ch in str(text))
    except Exception:
        return False


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    dp = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        dp[i][0] = i
    for j in range(len(b) + 1):
        dp[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(
                dp[i - 1][j] + 1,        # deletion
                dp[i][j - 1] + 1,        # insertion
                dp[i - 1][j - 1] + cost, # substitution
            )
    return dp[len(a)][len(b)]


def keyboard_adjacent_similarity(a: str, b: str) -> bool:
    # Minimal heuristic: typical homograph swaps
    swaps = {
        "0": "o",
        "1": "l",
        "l": "1",
        "o": "0",
        "rn": "m",
        "vv": "w",
        "5": "s",
        "$": "s",
    }
    a2 = a
    for k, v in swaps.items():
        a2 = a2.replace(k, v)
    return a2 == b


def is_lookalike_domain(domain: str | None, known_brands: List[str] | None = None) -> Tuple[bool, str | None]:
    d = normalize_domain(domain)
    if not d:
        return False, None
    brands = known_brands or KNOWN_BRANDS
    for brand in brands:
        if d == brand:
            return False, None
        dist = levenshtein(d, brand)
        if dist <= 1 or keyboard_adjacent_similarity(d, brand):
            return True, brand
    return False, None


def reply_to_mismatch(from_addr: str | None, reply_to: str | None) -> bool:
    fd = extract_domain(from_addr)
    rd = extract_domain(reply_to)
    if not fd or not rd:
        return False
    return fd != rd


def extract_iocs(text: str, *, tenant_id: str | None = None) -> List[Dict[str, Any]]:
    thresholds = _get_thresholds(tenant_id=tenant_id)
    domain_deny = thresholds.get("DOMAIN_DENYLIST", []) or []
    domain_allow = thresholds.get("DOMAIN_ALLOWLIST", []) or []
    ip_deny = thresholds.get("IP_DENYLIST", []) or []
    ip_allow = thresholds.get("IP_ALLOWLIST", []) or []
    iocs: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    # URLs
    for m in re.finditer(r"https?://[^\s<>()\"']+", text):
        url = m.group(0)
        try:
            parsed = urlparse(url)
            dom = normalize_domain(parsed.hostname)
        except Exception:
            dom_m = re.search(r"https?://([^/]+)", url)
            dom = normalize_domain(dom_m.group(1) if dom_m else None)
        key = ("url", url)
        if key not in seen:
            seen.add(key)
            iocs.append(
                {
                    "type": "url",
                    "value": url,
                    "domain": dom,
                    "denylisted": bool(dom) and dom in set(map(str, domain_deny)),
                    "allowlisted": bool(dom) and dom in set(map(str, domain_allow)),
                    "source": "body_text",
                    "source_confidence": 0.78,
                }
            )
    # Domains
    for m in re.finditer(r"\b([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b", text):
        dom = normalize_domain(m.group(1))
        if not dom:
            continue
        key = ("domain", dom)
        if key not in seen:
            seen.add(key)
            iocs.append(
                {
                    "type": "domain",
                    "value": dom,
                    "denylisted": dom in set(map(str, domain_deny)),
                    "allowlisted": dom in set(map(str, domain_allow)),
                    "source": "body_text",
                    "source_confidence": 0.72,
                }
            )
    # IPs
    for m in re.finditer(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        ip = m.group(0)
        key = ("ip", ip)
        if key not in seen:
            seen.add(key)
            iocs.append(
                {
                    "type": "ip",
                    "value": ip,
                    "denylisted": ip in set(map(str, ip_deny)),
                    "allowlisted": ip in set(map(str, ip_allow)),
                    "source": "body_text",
                    "source_confidence": 0.66,
                }
            )
    return iocs


def extract_attachment_hash_iocs(attachments: List[Dict[str, Any]] | None, *, tenant_id: str | None = None) -> List[Dict[str, Any]]:
    thresholds = _get_thresholds(tenant_id=tenant_id)
    hash_deny = set([str(x).lower() for x in (thresholds.get("HASH_DENYLIST", []) or [])])
    hash_allow = set([str(x).lower() for x in (thresholds.get("HASH_ALLOWLIST", []) or [])])
    out: List[Dict[str, Any]] = []
    for a in (attachments or []):
        hv = str((a or {}).get("sha256") or "").strip().lower()
        if not hv:
            name = str((a or {}).get("name") or "")
            if not name:
                continue
            hv = hashlib.sha256(name.encode("utf-8")).hexdigest()
        out.append(
            {
                "type": "hash",
                "value": hv,
                "denylisted": hv in hash_deny,
                "allowlisted": hv in hash_allow,
                "source": "attachment_hash",
                "source_confidence": 0.92,
            }
        )
    return out


def detect_keywords(text: str) -> List[str]:
    risky = [
        r"urgent",
        r"wire\s+transfer",
        r"gift\s*cards",
        r"asap",
        r"confidential",
        r"bank\s+details",
        r"invoice",
        r"payment",
        r"overdue",
    ]
    found: List[str] = []
    low = text.lower()
    for kw in risky:
        if re.search(kw, low):
            found.append(kw)
    return found


def detect_anomaly(text: str) -> List[str]:
    thr = _get_thresholds()
    long_len = int(thr.get("ANOMALY_LONG_TOKEN_LEN", 500))
    repeat_min = int(thr.get("ANOMALY_REPEAT_MIN", 50))
    anomalies: List[str] = []
    # Long token
    if re.search(rf"\b\w{{{long_len},}}\b", text):
        anomalies.append("long_token")
    # Excessive repeats
    if re.search(rf"(.)\1{{{repeat_min},}}", text):
        anomalies.append("repeat_chars")
    return anomalies


def suspicious_attachments(attachments: List[Dict[str, Any]] | None) -> List[str]:
    if not attachments:
        return []
    suspicious_ext = {
        ".html", ".htm", ".exe", ".js", ".scr", ".bat", ".cmd", ".ps1", ".vbs",
        ".lnk", ".iso", ".img", ".hta", ".jar", ".chm", ".docm", ".xlsm",
    }
    hits: List[str] = []
    for a in attachments:
        name = (a.get("name") or "").lower()
        for ext in suspicious_ext:
            if name.endswith(ext):
                hits.append(name)
                break
    return hits


def url_redirect_chain_risk(urls: List[str] | None) -> Dict[str, Any]:
    score = 0.0
    flags: List[str] = []
    suspicious: List[str] = []
    for u in (urls or []):
        try:
            p = urlparse(u)
            host = (p.hostname or "").lower()
            path = (p.path or "").lower()
            qs = parse_qs(p.query or "")
            if host in _URL_SHORTENER_DOMAINS:
                score += 0.35
                flags.append("shortener_domain")
            if "@" in (p.netloc or ""):
                score += 0.25
                flags.append("userinfo_in_url")
            if re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", host):
                score += 0.25
                flags.append("ip_literal_host")
            if host.startswith("xn--") or ".xn--" in host:
                score += 0.25
                flags.append("punycode_domain")
            if any(k in qs for k in ("redirect", "url", "next", "dest", "target")):
                score += 0.15
                flags.append("redirect_param")
            if any(seg in path for seg in ("/login", "/verify", "/auth", "/pay")):
                score += 0.1
                flags.append("credential_or_payment_lure")
            if score >= 0.45:
                suspicious.append(u[:300])
        except Exception:
            continue
    return {
        "score": round(min(1.0, score), 3),
        "flags": sorted(set(flags)),
        "suspicious_urls": suspicious[:5],
    }


def attachment_static_triage(attachments: List[Dict[str, Any]] | None) -> Dict[str, Any]:
    findings: List[str] = []
    risky: List[str] = []
    score = 0.0
    for a in (attachments or []):
        name = str((a or {}).get("name") or "").lower()
        ctype = str((a or {}).get("content_type") or "").lower()
        if not name:
            continue
        if name.endswith((".docm", ".xlsm", ".pptm")):
            score += 0.45
            findings.append("macro_enabled_office_doc")
            risky.append(name)
        if name.endswith((".lnk", ".iso", ".img", ".hta", ".js", ".vbs", ".ps1", ".chm", ".exe", ".scr", ".cmd", ".bat")):
            score += 0.5
            findings.append("script_or_loader_attachment")
            risky.append(name)
        if "macro" in name or "enable_content" in name or "enable-content" in name:
            score += 0.2
            findings.append("macro_lure_filename")
            risky.append(name)
        if "octet-stream" in ctype or "msdownload" in ctype:
            score += 0.1
            findings.append("opaque_or_executable_mime")
            risky.append(name)
    return {
        "score": round(min(1.0, score), 3),
        "flags": sorted(set(findings)),
        "risky_attachments": sorted(set(risky))[:10],
    }


def extract_indicators(email: Dict[str, Any], *, tenant_id: str | None = None) -> Dict[str, Any]:
    """Extract typed indicators from an email-like dict.

    Expected keys: subject, body, from_addr, reply_to, attachments (optional list).
    """
    subject = str(email.get("subject") or "")
    body = str(email.get("body") or "")
    attachments = email.get("attachments") or []
    text = f"{subject}\n{body}"
    # Scan attachment extracted text for advanced threats (OCR/QR overlays, embedded instructions)
    # while keeping core BEC wording checks body-focused to reduce false positives.
    attachment_text = "\n".join(
        str((a or {}).get("extracted_text") or "")[:4000]
        for a in attachments
        if str((a or {}).get("extracted_text") or "").strip()
    )[:40000]
    analysis_text = f"{text}\n{attachment_text}" if attachment_text else text
    from_addr = email.get("from_addr")
    reply_to = email.get("reply_to")
    thresholds = _get_thresholds(tenant_id=tenant_id)

    indicators: List[Dict[str, Any]] = []

    # Reply-To mismatch
    if reply_to_mismatch(from_addr, reply_to):
        indicators.append({"type": "reply_to_mismatch", "value": True, "reason": "From vs Reply-To domain mismatch"})

    # Lookalike/homoglyph domain checks
    from_domain_norm = extract_domain(from_addr)
    reply_domain_norm = extract_domain(reply_to)
    lookalike, brand = is_lookalike_domain(from_domain_norm)
    if lookalike:
        indicators.append({"type": "lookalike_domain", "value": from_domain_norm, "reason": f"Similar to {brand}"})
    try:
        from_skel = _confusable_skeleton(from_domain_norm)
        reply_skel = _confusable_skeleton(reply_domain_norm)
        vendor_domain_norm = normalize_domain(str(email.get("vendor_domain") or "").strip().lower())
        vendor_skel = _confusable_skeleton(vendor_domain_norm)
        if _has_non_ascii(from_domain_norm) and from_skel and from_skel != (from_domain_norm or ""):
            indicators.append(
                {
                    "type": "confusable_homoglyph_domain",
                    "value": from_domain_norm,
                    "reason": "Sender domain contains confusable Unicode characters",
                }
            )
        if vendor_skel and from_skel and vendor_skel == from_skel and vendor_domain_norm != from_domain_norm:
            indicators.append(
                {
                    "type": "vendor_homoglyph_impersonation",
                    "value": from_domain_norm,
                    "reason": f"Sender visually impersonates vendor domain {vendor_domain_norm}",
                }
            )
        if reply_skel and from_skel and reply_skel != from_skel and _has_non_ascii(reply_domain_norm):
            indicators.append(
                {
                    "type": "reply_to_confusable_mismatch",
                    "value": reply_domain_norm,
                    "reason": "Reply-To contains confusable Unicode domain mismatch",
                }
            )
    except Exception:
        pass

    # Keywords
    kws = detect_keywords(text)
    for kw in kws:
        indicators.append({"type": "keyword", "value": kw, "reason": "Suspicious phrasing"})

    # Anomalies
    for an in detect_anomaly(text):
        indicators.append({"type": "anomaly", "value": an, "reason": "Anomalous structure"})

    # Attachments
    for name in suspicious_attachments(attachments):
        indicators.append({"type": "suspicious_attachment", "value": name, "reason": "Potentially risky attachment"})

    # SPF/DKIM/DMARC deterministic auth policy gate
    spf_result = str(email.get("spf_result") or "").strip().lower()
    dkim_result = str(email.get("dkim_result") or "").strip().lower()
    dmarc_result = str(email.get("dmarc_result") or "").strip().lower()
    dmarc_policy = str(email.get("dmarc_policy") or "").strip().lower()
    dmarc_fail = bool(email.get("dmarc_fail", False))
    arc_cv = str(email.get("arc_cv") or "").strip().lower()
    arc_chain_valid = email.get("arc_chain_valid")
    bimi_result = str(email.get("bimi_result") or "").strip().lower()
    bimi_present = bool(email.get("bimi_present")) or bool(email.get("bimi_location"))
    if not dmarc_fail and dmarc_result in ("fail", "quarantine", "reject"):
        dmarc_fail = True
    if spf_result in ("fail", "softfail") and dkim_result in ("fail", "neutral", "") and dmarc_policy in ("reject", "p=reject", "quarantine", "p=quarantine"):
        indicators.append(
            {
                "type": "auth_enforcement",
                "value": "dmarc_policy_enforcement",
                "reason": f"SPF={spf_result or 'n/a'} DKIM={dkim_result or 'n/a'} DMARC={dmarc_policy or dmarc_result or 'n/a'}",
            }
        )
    elif spf_result == "softfail" or dkim_result == "neutral":
        indicators.append(
            {
                "type": "auth_softfail",
                "value": "spf_dkim_softfail",
                "reason": f"SPF={spf_result or 'n/a'} DKIM={dkim_result or 'n/a'}",
            }
        )
    if arc_cv == "fail" or arc_chain_valid is False:
        indicators.append(
            {
                "type": "arc_chain_invalid",
                "value": arc_cv or "fail",
                "reason": "ARC chain verification failed; forwarded authentication context untrusted",
            }
        )
    elif arc_cv == "pass" or arc_chain_valid is True:
        indicators.append(
            {
                "type": "arc_chain_valid",
                "value": "pass",
                "reason": "ARC chain present and valid",
            }
        )
    if bimi_present and bimi_result in ("fail", "temperror", "permerror"):
        indicators.append(
            {
                "type": "bimi_validation_failed",
                "value": bimi_result,
                "reason": "BIMI indicator present but validation failed",
            }
        )
    elif bimi_present and bimi_result == "pass":
        indicators.append(
            {
                "type": "bimi_validated",
                "value": "pass",
                "reason": "BIMI validation passed",
            }
        )

    # External sender tagging + display-name/domain mismatch
    external_sender = email.get("external_sender")
    if external_sender is None:
        internal_domains = set([str(x).lower() for x in (thresholds.get("INTERNAL_EMAIL_DOMAINS", []) or [])])
        fd = str(extract_domain(from_addr) or "").lower()
        external_sender = bool(fd and internal_domains and fd not in internal_domains)
    if bool(external_sender):
        indicators.append({"type": "external_sender", "value": True, "reason": "Sender outside tenant boundary"})

    # Supplier payment/BEC controls
    if _BANK_CHANGE_PAT.search(text):
        indicators.append({"type": "bank_change_request", "value": True, "reason": "Payment destination change requested"})
    if _INVOICE_REDIRECT_PAT.search(text):
        indicators.append({"type": "invoice_redirect", "value": True, "reason": "Invoice/remittance redirection pattern"})
    if _URGENCY_PAT.search(text):
        indicators.append({"type": "urgency_language", "value": True, "reason": "Urgency/pressure language"})
    vendor_domain = str(email.get("vendor_domain") or "").strip().lower()
    from_domain = str(from_domain_norm or "").strip().lower()
    trusted_vendor_domains = set([str(x).lower() for x in (thresholds.get("TRUSTED_VENDOR_DOMAINS", []) or [])])
    if vendor_domain and from_domain and vendor_domain != from_domain:
        indicators.append({"type": "vendor_domain_mismatch", "value": from_domain, "reason": f"Expected vendor domain {vendor_domain}"})
    if trusted_vendor_domains and from_domain and from_domain not in trusted_vendor_domains:
        indicators.append({"type": "vendor_untrusted_domain", "value": from_domain, "reason": "Sender domain not in trusted vendor baseline"})
    bank_fp = str(email.get("bank_fingerprint") or "").strip()
    proposed_fp = str(email.get("proposed_bank_fingerprint") or "").strip()
    if bank_fp and proposed_fp and bank_fp != proposed_fp:
        indicators.append({"type": "bank_fingerprint_mismatch", "value": "changed", "reason": "Vendor bank fingerprint changed"})
        indicators.append({"type": "oob_verification_required", "value": True, "reason": "Out-of-band verification mandatory"})
    if bool(email.get("oob_verified")):
        indicators.append({"type": "oob_verification_completed", "value": True, "reason": "Out-of-band verification completed"})
    chain = str(email.get("reply_chain_id") or "").strip()
    prior_chain = str(email.get("prior_reply_chain_id") or "").strip()
    if chain and prior_chain and chain != prior_chain:
        indicators.append({"type": "reply_chain_hijack", "value": chain, "reason": "Reply-chain continuity mismatch"})

    # OCR overlay tuning: distinguish benign catalog overlays from payment/malicious overlays.
    if attachment_text:
        overlay_text = str(attachment_text or "")[:20000]
        overlay_has_payment = bool(_OCR_OVERLAY_PAYMENT_PAT.search(overlay_text))
        overlay_has_malicious = bool(
            _PROMPT_INJECTION_PAT.search(overlay_text)
            or _DANGEROUS_TOOL_PAT.search(overlay_text)
            or _EXFIL_PAT.search(overlay_text)
            or _C2_BEACON_PAT.search(overlay_text)
            or _FILELESS_PAT.search(overlay_text)
        )
        overlay_benign_catalog = bool(_OCR_OVERLAY_BENIGN_CATALOG_PAT.search(overlay_text)) and not overlay_has_payment and not overlay_has_malicious
        if overlay_has_malicious:
            indicators.append(
                {
                    "type": "ocr_overlay_malicious_text",
                    "value": True,
                    "reason": "Attachment OCR text contains malicious instruction patterns",
                }
            )
            # Keep legacy/high-signal tags so downstream policy + regressions
            # treat OCR-borne prompt payloads the same as body-borne payloads.
            indicators.append(
                {
                    "type": "prompt_injection",
                    "value": True,
                    "reason": "Prompt injection pattern detected in attachment OCR text",
                }
            )
            if _DANGEROUS_TOOL_PAT.search(overlay_text):
                indicators.append(
                    {
                        "type": "dangerous_tool_intent",
                        "value": True,
                        "reason": "Disallowed tool intent detected in attachment OCR text",
                    }
                )
        elif overlay_has_payment:
            indicators.append(
                {
                    "type": "ocr_overlay_payment_instruction",
                    "value": True,
                    "reason": "Attachment OCR text includes payment/QR remittance instructions",
                }
            )
            try:
                norm_overlay = unicodedata.normalize("NFKC", overlay_text.lower())
                skel_overlay = _confusable_skeleton(overlay_text)
                if _has_non_ascii(overlay_text) and skel_overlay and skel_overlay != norm_overlay:
                    indicators.append(
                        {
                            "type": "ocr_overlay_unicode_confusable_payment",
                            "value": True,
                            "reason": "Attachment OCR payment text contains confusable Unicode characters",
                        }
                    )
            except Exception:
                pass
        elif overlay_benign_catalog:
            indicators.append(
                {
                    "type": "ocr_overlay_benign_catalog",
                    "value": True,
                    "reason": "Attachment OCR text appears to be benign catalog/specification content",
                }
            )

    # Agent/LLM control indicators
    if _PROMPT_INJECTION_PAT.search(analysis_text):
        indicators.append({"type": "prompt_injection", "value": True, "reason": "Prompt injection pattern detected"})
    if _DANGEROUS_TOOL_PAT.search(analysis_text):
        indicators.append({"type": "dangerous_tool_intent", "value": True, "reason": "Disallowed tool intent in content"})
    lolbin_hits = sorted({m.group(1).lower() for m in _LOLBINS_PAT.finditer(analysis_text)})
    if lolbin_hits:
        indicators.append({"type": "lolbin_command", "value": lolbin_hits, "reason": "Living-off-the-land binary pattern detected"})
        has_external_link = bool(re.search(r"https?://", analysis_text))
        has_risky_attachment = bool(suspicious_attachments(attachments))
        if has_external_link or has_risky_attachment:
            indicators.append(
                {
                    "type": "lolbin_delivery_combo",
                    "value": True,
                    "reason": "LOLBin command combined with external link/attachment",
                }
            )
    if _RANSOMWARE_PAT.search(analysis_text):
        indicators.append({"type": "ransomware_extortion_pattern", "value": True, "reason": "Ransomware/extortion language detected"})
    if _EXFIL_PAT.search(analysis_text):
        indicators.append({"type": "data_exfil_intent", "value": True, "reason": "Data exfiltration pattern detected"})
    if _KEYLOGGER_PAT.search(analysis_text):
        indicators.append({"type": "keylogger_pattern", "value": True, "reason": "Keylogger/credential-harvester pattern detected"})
    if _C2_BEACON_PAT.search(analysis_text):
        indicators.append({"type": "c2_beacon_pattern", "value": True, "reason": "C2 beacon/callback pattern detected"})
    if _FILELESS_PAT.search(analysis_text):
        indicators.append({"type": "fileless_execution_pattern", "value": True, "reason": "Fileless execution pattern detected"})
    try:
        risky_names = suspicious_attachments(attachments)
        if risky_names and (
            _FILELESS_PAT.search(analysis_text)
            or _KEYLOGGER_PAT.search(analysis_text)
            or _EXFIL_PAT.search(analysis_text)
            or _RANSOMWARE_PAT.search(analysis_text)
        ):
            indicators.append(
                {
                    "type": "malware_delivery_combo",
                    "value": True,
                    "reason": "Suspicious attachment combined with malware/exfil execution patterns",
                }
            )
    except Exception:
        pass

    # P2 fuzzy/canary
    if _CANARY_PAT.search(analysis_text):
        indicators.append({"type": "canary_token_triggered", "value": True, "reason": "Canary marker detected"})
    # URL detonation/redirect-chain and attachment static triage (oletools-style metadata checks).
    try:
        urls = [str(x.get("value") or "") for x in extract_iocs(analysis_text, tenant_id=tenant_id) if str(x.get("type") or "") == "url"]
        url_triage = url_redirect_chain_risk(urls)
        if float(url_triage.get("score") or 0.0) >= 0.45:
            indicators.append(
                {
                    "type": "url_detonation_high_risk",
                    "value": url_triage,
                    "reason": "URL redirect-chain/callback triage indicates elevated risk",
                }
            )
        elif float(url_triage.get("score") or 0.0) >= 0.25:
            indicators.append(
                {
                    "type": "url_detonation_medium_risk",
                    "value": url_triage,
                    "reason": "URL redirect-chain triage indicates medium risk",
                }
            )
    except Exception:
        pass
    try:
        att_triage = attachment_static_triage(attachments)
        if float(att_triage.get("score") or 0.0) >= 0.45:
            indicators.append(
                {
                    "type": "attachment_static_triage_high_risk",
                    "value": att_triage,
                    "reason": "Attachment static triage indicates likely malware delivery vector",
                }
            )
        elif float(att_triage.get("score") or 0.0) >= 0.2:
            indicators.append(
                {
                    "type": "attachment_static_triage_medium_risk",
                    "value": att_triage,
                    "reason": "Attachment static triage indicates moderate risk",
                }
            )
    except Exception:
        pass
    simhash = hashlib.sha256(re.sub(r"\\s+", " ", text.lower()).encode("utf-8")).hexdigest()[:16]
    indicators.append({"type": "simhash_fingerprint", "value": simhash, "reason": "Near-duplicate clustering fingerprint"})

    # IoCs
    iocs = extract_iocs(analysis_text, tenant_id=tenant_id)
    iocs.extend(extract_attachment_hash_iocs(attachments, tenant_id=tenant_id))

    return {
        "indicators": indicators,
        "iocs": iocs,
        "meta": {
            "from_domain": extract_domain(from_addr),
            "reply_to_domain": extract_domain(reply_to),
            "external_sender": bool(external_sender),
            "auth": {
                "spf_result": spf_result or None,
                "dkim_result": dkim_result or None,
                "dmarc_result": dmarc_result or None,
                "dmarc_policy": dmarc_policy or None,
                "dmarc_fail": bool(dmarc_fail),
                "arc_cv": arc_cv or None,
                "arc_chain_valid": bool(arc_chain_valid) if arc_chain_valid is not None else None,
                "bimi_result": bimi_result or None,
                "bimi_present": bool(bimi_present),
            },
        },
    }

