from __future__ import annotations

import ipaddress
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, parseaddr
from typing import Any, Dict, List

from src.app.services.geoip import enrich_ip


_MSGID_CACHE: dict[str, float] = {}
_BULK_MAILER_HINTS = (
    "mailchimp",
    "sendgrid",
    "phpmailer",
    "python-requests",
    "smtp client",
    "mass mailer",
    "bulk",
)
_MAX_CACHE_SIZE = 50000
_RE_MSG_ID = re.compile(r"^\s*<([^<>@]+)@([^<>@]+)>\s*$")
_RE_RECEIVED_FROM = re.compile(r"from\s+([^\s;]+)", re.IGNORECASE)
_RE_RECEIVED_BY = re.compile(r"by\s+([^\s;]+)", re.IGNORECASE)
_RE_RECEIVED_IP = re.compile(r"\[([0-9a-fA-F:.]+)\]")


def _norm_domain(addr_or_domain: str | None) -> str | None:
    if not addr_or_domain:
        return None
    raw = str(addr_or_domain).strip()
    if "@" in raw:
        raw = str(parseaddr(raw)[1] or raw).strip()
        if "@" in raw:
            raw = raw.rsplit("@", 1)[-1]
    raw = raw.strip().strip("<>").strip().lower().rstrip(".,;:")
    return raw or None


def _parse_headers(email: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    headers = email.get("headers")
    if isinstance(headers, dict):
        for k, v in headers.items():
            if k is None:
                continue
            out[str(k).lower()] = str(v or "")
    elif isinstance(headers, list):
        for item in headers:
            if isinstance(item, dict):
                k = str(item.get("name") or item.get("key") or "").strip().lower()
                if k:
                    out[k] = str(item.get("value") or "")
    if not out.get("message-id") and email.get("message_id"):
        out["message-id"] = str(email.get("message_id") or "")
    if not out.get("x-originating-ip") and email.get("x_originating_ip"):
        out["x-originating-ip"] = str(email.get("x_originating_ip") or "")
    if not out.get("x-mailer") and email.get("x_mailer"):
        out["x-mailer"] = str(email.get("x_mailer") or "")
    return out


def _parse_received_chain(email: Dict[str, Any], headers: Dict[str, str]) -> List[Dict[str, Any]]:
    vals: List[str] = []
    if isinstance(email.get("received_headers"), list):
        vals.extend([str(x) for x in (email.get("received_headers") or []) if str(x or "").strip()])
    if headers.get("received"):
        vals.append(str(headers.get("received") or ""))
    chain: List[Dict[str, Any]] = []
    for idx, raw in enumerate(vals):
        parts = str(raw).split(";")
        route = parts[0] if parts else str(raw)
        ts_raw = parts[-1].strip() if len(parts) > 1 else ""
        ts = None
        try:
            dt = parsedate_to_datetime(ts_raw)
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = dt.isoformat() if dt else None
        except Exception:
            ts = None
        from_host = None
        by_host = None
        ip = None
        m_from = _RE_RECEIVED_FROM.search(route or "")
        m_by = _RE_RECEIVED_BY.search(route or "")
        m_ip = _RE_RECEIVED_IP.search(route or "")
        if m_from:
            from_host = m_from.group(1).strip()
        if m_by:
            by_host = m_by.group(1).strip()
        if m_ip:
            ip = m_ip.group(1).strip()
        chain.append(
            {
                "index": idx,
                "raw": raw[:400],
                "from_host": from_host,
                "by_host": by_host,
                "relay_ip": ip,
                "timestamp": ts,
            }
        )
    return chain


def _message_id_analysis(message_id: str | None, from_addr: str | None, *, ttl_seconds: int = 24 * 3600) -> Dict[str, Any]:
    now = time.time()
    try:
        expired = [k for k, exp in _MSGID_CACHE.items() if exp <= now]
        for k in expired[:2000]:
            _MSGID_CACHE.pop(k, None)
    except Exception:
        pass
    mid = str(message_id or "").strip()
    valid = False
    domain = None
    mismatch = False
    reuse = False
    if mid:
        m = _RE_MSG_ID.match(mid)
        if m:
            valid = True
            domain = _norm_domain(m.group(2))
        from_dom = _norm_domain(from_addr)
        if from_dom and domain and from_dom != domain:
            mismatch = True
        if mid in _MSGID_CACHE:
            reuse = True
        _MSGID_CACHE[mid] = now + max(60, int(ttl_seconds))
        if len(_MSGID_CACHE) > _MAX_CACHE_SIZE:
            # best-effort prune
            for k in list(_MSGID_CACHE.keys())[: int(_MAX_CACHE_SIZE * 0.1)]:
                _MSGID_CACHE.pop(k, None)
    return {
        "message_id_valid": bool(valid),
        "message_id_domain": domain,
        "message_id_domain_mismatch": bool(mismatch),
        "message_id_reuse": bool(reuse),
    }


def analyze_email_headers(email: Dict[str, Any], *, replay_ttl_seconds: int = 24 * 3600) -> Dict[str, Any]:
    headers = _parse_headers(email)
    from_addr = str(email.get("from_addr") or "")
    message_id = str(headers.get("message-id") or email.get("message_id") or "")
    x_mailer = str(headers.get("x-mailer") or "")
    x_originating_ip = str(headers.get("x-originating-ip") or "").strip().strip("[]")
    relay_chain = _parse_received_chain(email, headers)
    msgid = _message_id_analysis(message_id, from_addr, ttl_seconds=replay_ttl_seconds)

    header_injection_detected = False
    try:
        for _k, v in headers.items():
            vv = str(v or "")
            if "\x00" in vv or "\r\n" in vv:
                header_injection_detected = True
                break
            if len(vv) > 998:
                header_injection_detected = True
                break
    except Exception:
        header_injection_detected = False

    timing_anomaly = False
    relay_count_anomaly = False
    timestamps: List[datetime] = []
    for hop in relay_chain:
        ts = hop.get("timestamp")
        if ts:
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                timestamps.append(dt)
            except Exception:
                continue
    if len(relay_chain) > 12:
        relay_count_anomaly = True
    if len(timestamps) >= 2:
        # Received headers should generally be monotonic (most-recent first).
        for i in range(len(timestamps) - 1):
            if timestamps[i] < timestamps[i + 1]:
                timing_anomaly = True
                break
        now = datetime.now(timezone.utc)
        if any(ts > now for ts in timestamps):
            timing_anomaly = True

    originating_ip_risk = 0.0
    originating_ip_geo = {}
    if x_originating_ip:
        try:
            ipaddress.ip_address(x_originating_ip)
            originating_ip_geo = enrich_ip(x_originating_ip) or {}
            originating_ip_risk = float(originating_ip_geo.get("risk") or 0.0)
        except Exception:
            originating_ip_risk = 0.85
    mailer_l = x_mailer.lower()
    mailer_is_bulk = any(h in mailer_l for h in _BULK_MAILER_HINTS) if x_mailer else False

    risk = 0.0
    if msgid.get("message_id_valid") is False and message_id:
        risk += 0.12
    if msgid.get("message_id_domain_mismatch"):
        risk += 0.18
    if msgid.get("message_id_reuse"):
        risk += 0.22
    if header_injection_detected:
        risk += 0.22
    if timing_anomaly:
        risk += 0.2
    if relay_count_anomaly:
        risk += 0.12
    if mailer_is_bulk:
        risk += 0.1
    risk += min(0.3, max(0.0, float(originating_ip_risk)) * 0.3)
    risk = max(0.0, min(1.0, round(risk, 4)))

    return {
        "relay_chain": relay_chain,
        "originating_ip": x_originating_ip or None,
        "originating_ip_geo": originating_ip_geo,
        "originating_ip_risk": round(float(originating_ip_risk), 4),
        "mailer_fingerprint": x_mailer or None,
        "mailer_is_bulk": bool(mailer_is_bulk),
        "message_id_valid": bool(msgid.get("message_id_valid")),
        "message_id_domain_mismatch": bool(msgid.get("message_id_domain_mismatch")),
        "message_id_reuse": bool(msgid.get("message_id_reuse")),
        "header_injection_detected": bool(header_injection_detected),
        "timing_anomaly": bool(timing_anomaly),
        "relay_count_anomaly": bool(relay_count_anomaly),
        "risk_score": risk,
    }
