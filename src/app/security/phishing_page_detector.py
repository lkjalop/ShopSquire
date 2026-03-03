from __future__ import annotations

from typing import Any, Dict, List
import hashlib
import json
import re
import time
from urllib.parse import urlparse


def _hash24(value: str | None) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _url_signals(url: str) -> Dict[str, Any]:
    u = str(url or "").strip()
    p = urlparse(u)
    host = str(p.netloc or "").lower()
    path = str(p.path or "").lower()
    reasons: List[str] = []
    score = 0.0
    if not host:
        return {"host": "", "score": 0.0, "reasons": ["invalid_url"]}
    if "xn--" in host:
        score += 0.22
        reasons.append("punycode_host")
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", host):
        score += 0.24
        reasons.append("ip_literal_host")
    if any(x in host for x in ("ngrok", "pages.dev", "github.io", "vercel.app", "netlify.app")):
        score += 0.12
        reasons.append("ephemeral_hosting_platform")
    if any(x in (host + path) for x in ("login", "verify", "password", "signin", "oauth", "mfa", "invoice", "wire")):
        score += 0.2
        reasons.append("credential_or_payment_lure_token")
    if "@" in u:
        score += 0.12
        reasons.append("at_sign_obfuscation")
    if len(host.split(".")) >= 4:
        score += 0.10
        reasons.append("deep_subdomain")
    return {"host": host, "score": round(min(1.0, score), 4), "reasons": reasons}


def analyze_phishing_targets(
    urls: List[str],
    *,
    enrichment: Dict[str, Any] | None = None,
    detonation: Dict[str, Any] | None = None,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """Prepare an async phishing-page analysis stage and emit immediate URL risk hints."""
    unique_urls = []
    seen = set()
    for u in urls or []:
        s = str(u or "").strip()
        if s and s not in seen:
            seen.add(s)
            unique_urls.append(s)
    if not unique_urls:
        return {
            "stage": "skipped",
            "reason": "no_urls",
            "queued": False,
            "detected": False,
            "max_risk_score": 0.0,
            "items": [],
            "indicators": [],
        }

    items = []
    max_score = 0.0
    for u in unique_urls[:40]:
        sig = _url_signals(u)
        score = float(sig.get("score") or 0.0)
        # Correlate with existing IOC and detonation stages.
        if int((enrichment or {}).get("malicious_hits") or 0) > 0:
            score += 0.15
        if bool((detonation or {}).get("malicious")):
            score += 0.2
        score = round(min(1.0, score), 4)
        max_score = max(max_score, score)
        items.append(
            {
                "url_hash": _hash24(u),
                "host": sig.get("host"),
                "risk_score": score,
                "reasons": sig.get("reasons") or [],
            }
        )

    indicators: List[Dict[str, Any]] = []
    if max_score >= 0.7:
        indicators.append(
            {
                "type": "phishing_landing_page_high_risk",
                "value": round(max_score, 4),
                "reason": "Phishing landing page pre-analysis exceeded risk threshold",
            }
        )
    elif max_score >= 0.5:
        indicators.append(
            {
                "type": "phishing_landing_page_review",
                "value": round(max_score, 4),
                "reason": "Phishing landing page pre-analysis requires analyst review",
            }
        )

    job_id = f"pp-{_hash24(str(time.time()))}"
    queued = False
    try:
        from src.app.deps import get_redis

        r = get_redis()
        if r.__class__.__name__ != "DummyRedis":
            payload = {
                "job_id": job_id,
                "tenant_id": tenant_id,
                "queued_at": int(time.time()),
                "urls": unique_urls[:40],
            }
            r.lpush("email_security:phishing_page_jobs", json.dumps(payload))
            queued = True
    except Exception:
        queued = False

    return {
        "stage": "queued" if queued else "prepared",
        "queued": queued,
        "job_id": job_id,
        "detected": bool(indicators),
        "max_risk_score": round(max_score, 4),
        "items": items,
        "indicators": indicators,
    }


def run_phishing_page_deep_analysis(urls: List[str]) -> Dict[str, Any]:
    """Worker-side deep analysis for queued phishing page targets."""
    url_list = [str(u or "").strip() for u in (urls or []) if str(u or "").strip()][:40]
    if not url_list:
        return {"malicious": False, "max_risk_score": 0.0, "items": [], "findings": []}

    findings: List[str] = []
    items: List[Dict[str, Any]] = []
    max_score = 0.0
    fetch_enabled = str(__import__("os").getenv("PHISHING_PAGE_FETCH_ENABLED", "0") or "0").strip().lower() in ("1", "true", "yes", "on")

    for u in url_list:
        sig = _url_signals(u)
        score = float(sig.get("score") or 0.0)
        reasons = list(sig.get("reasons") or [])
        html_text = ""
        if fetch_enabled:
            try:
                from src.app.security.safe_requests import safe_request

                resp = safe_request("GET", u, timeout=4.0, allow_redirects=True)
                ctype = str((resp.headers or {}).get("content-type") or "").lower()
                if "html" in ctype:
                    html_text = str(resp.text or "")[:20000].lower()
            except Exception:
                pass
        if html_text:
            if "<form" in html_text and any(tok in html_text for tok in ("password", "passcode", "otp", "mfa", "verify identity")):
                score += 0.28
                reasons.append("credential_harvest_form_pattern")
            if any(tok in html_text for tok in ("wallet connect", "seed phrase", "private key")):
                score += 0.25
                reasons.append("wallet_seed_phrase_harvest_pattern")
            if any(tok in html_text for tok in ("urgent payment", "wire now", "invoice overdue", "bank details updated")):
                score += 0.18
                reasons.append("payment_redirection_lure_pattern")
        score = round(min(1.0, score), 4)
        max_score = max(max_score, score)
        if score >= 0.85:
            findings.append("high_confidence_phishing_landing_page")
        elif score >= 0.6:
            findings.append("suspicious_landing_page")
        items.append(
            {
                "url_hash": _hash24(u),
                "host": sig.get("host"),
                "risk_score": score,
                "reasons": reasons,
            }
        )

    malicious = bool(max_score >= 0.85 or "high_confidence_phishing_landing_page" in findings)
    return {
        "malicious": malicious,
        "max_risk_score": round(max_score, 4),
        "items": items,
        "findings": sorted(set(findings)),
    }
