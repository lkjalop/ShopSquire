from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urlparse


_BIMI_TXT_RE = re.compile(r"(?i)\bv\s*=\s*BIMI1\b")


def _extract_domain(from_addr: str | None) -> str:
    raw = str(from_addr or "").strip()
    if "@" not in raw:
        return ""
    # tolerate "Name <a@b.com>"
    if "<" in raw and ">" in raw:
        raw = raw.split("<", 1)[1].split(">", 1)[0]
    return raw.rsplit("@", 1)[-1].strip().lower()


def _dns_bimi_record(domain: str) -> Dict[str, Any]:
    if not domain:
        return {"ok": False, "error": "missing_domain"}
    qname = f"default._bimi.{domain}".strip(".")
    try:
        import dns.resolver  # type: ignore

        answers = dns.resolver.resolve(qname, "TXT")
        vals = []
        for a in answers:
            txt = "".join(
                [x.decode("utf-8", errors="ignore") if isinstance(x, (bytes, bytearray)) else str(x) for x in getattr(a, "strings", [])]
            )
            if not txt:
                txt = str(a).strip().strip('"')
            if txt:
                vals.append(txt)
        if not vals:
            return {"ok": False, "qname": qname, "error": "no_txt_records"}
        rec = vals[0]
        return {"ok": True, "qname": qname, "record": rec[:4096], "all_records": vals[:5]}
    except Exception as exc:
        return {"ok": False, "qname": qname, "error": str(exc)[:180]}


def _head_check(url: str) -> Dict[str, Any]:
    u = str(url or "").strip()
    if not u:
        return {"ok": False, "error": "missing_url"}
    try:
        p = urlparse(u)
        if p.scheme.lower() != "https":
            return {"ok": False, "error": "bimi_requires_https"}
    except Exception:
        return {"ok": False, "error": "invalid_url"}
    try:
        import requests

        r = requests.head(u, timeout=4.0, allow_redirects=True)
        ct = str((r.headers or {}).get("Content-Type") or "").lower()
        return {
            "ok": int(getattr(r, "status_code", 0) or 0) < 400,
            "status_code": int(getattr(r, "status_code", 0) or 0),
            "content_type": ct[:120],
            "final_url": str(getattr(r, "url", u) or u)[:2048],
            "svg_like": ("image/svg" in ct) or (".svg" in str(getattr(r, "url", u) or u).lower()),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:180]}


def verify_bimi_provider_backed(email: Dict[str, Any]) -> Dict[str, Any]:
    """Best-effort BIMI verification with provider headers + DNS + HTTPS asset checks."""
    e = email if isinstance(email, dict) else {}
    from_domain = _extract_domain(e.get("from_addr"))
    bimi_result = str(e.get("bimi_result") or "").strip().lower()
    bimi_location = str(e.get("bimi_location") or "").strip()
    provider_bimi_present = bool(e.get("bimi_present")) or bool(bimi_result) or bool(bimi_location)

    dns = _dns_bimi_record(from_domain) if from_domain else {"ok": False, "error": "missing_domain"}
    dns_record = str(dns.get("record") or "")
    dns_has_bimi = bool(_BIMI_TXT_RE.search(dns_record))
    location_check = _head_check(bimi_location) if bimi_location else {"ok": False, "error": "missing_location"}

    provider_pass = bimi_result == "pass"
    provider_fail = bimi_result in ("fail", "temperror", "permerror")
    verified = bool(provider_pass and dns_has_bimi and location_check.get("ok") and location_check.get("svg_like"))
    fail = bool(provider_fail or (provider_bimi_present and not verified))

    return {
        "from_domain": from_domain or None,
        "provider_bimi_present": provider_bimi_present,
        "provider_bimi_result": bimi_result or None,
        "dns": dns,
        "dns_has_bimi_record": dns_has_bimi,
        "location_check": location_check,
        "verified": verified,
        "failed": fail,
    }

