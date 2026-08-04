"""S-020 — Threat-intel API enrichment for QR-extracted URLs.

Checks QR-extracted URLs against external threat-intelligence feeds:
  1. URLhaus (abuse.ch) — free, no key needed, rate-limited
  2. VirusTotal — requires API key, rate-limited (4 req/min on free tier)
  3. Google Safe Browsing — requires API key

Falls back gracefully to heuristic-only scoring when APIs are unavailable
or rate-limited.  All API calls use strict timeouts and sanitized inputs.
Results are cached in SQLite to avoid redundant lookups.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.security.url_guard import ensure_safe_outbound_url

# API keys from env (optional — module degrades gracefully)
_VT_API_KEY = os.getenv("VIRUSTOTAL_API_KEY", "")
_GSB_API_KEY = os.getenv("GOOGLE_SAFE_BROWSING_KEY", "")

_CACHE_TTL_SEC = int(os.getenv("THREAT_INTEL_CACHE_TTL", "3600"))
_API_TIMEOUT_SEC = float(os.getenv("THREAT_INTEL_TIMEOUT", "5.0"))
_ASYNC_WORKERS = max(1, int(os.getenv("THREAT_INTEL_ASYNC_WORKERS", "2") or 2))
_INTEL_EXECUTOR = ThreadPoolExecutor(max_workers=_ASYNC_WORKERS)
_INTEL_INFLIGHT: set[str] = set()
_INTEL_INFLIGHT_LOCK = Lock()


def _ensure_tables() -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS threat_intel_cache (
                      url_hash TEXT PRIMARY KEY,
                      url_prefix TEXT,
                      source TEXT NOT NULL,
                      result_json TEXT NOT NULL,
                      queried_at INTEGER NOT NULL,
                      expires_at INTEGER NOT NULL
                    )
                    """
                )
            )
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS threat_intel_events (
                      id TEXT PRIMARY KEY,
                      url_prefix TEXT,
                      source TEXT NOT NULL,
                      malicious INTEGER NOT NULL DEFAULT 0,
                      detail_json TEXT,
                      created_at INTEGER NOT NULL
                    )
                    """
                )
            )
            db.commit()
    except Exception:
        pass


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _get_cached(url: str) -> Optional[Dict[str, Any]]:
    """Return cached result if still valid."""
    h = _url_hash(url)
    now = int(time.time())
    try:
        with db_session() as db:
            row = db.execute(
                text(
                    """
                    SELECT result_json FROM threat_intel_cache
                    WHERE url_hash = :h AND expires_at > :now
                    """
                ),
                {"h": h, "now": now},
            ).fetchone()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def get_cached_url_threat_intel(url: str) -> Optional[Dict[str, Any]]:
    """Public helper for callers that need low-latency cache-first behavior."""
    u = str(url or "").strip()
    if not u:
        return None
    _ensure_tables()
    return _get_cached(u)


def _store_cache(url: str, source: str, result: Dict[str, Any]) -> None:
    h = _url_hash(url)
    now = int(time.time())
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO threat_intel_cache
                    (url_hash, url_prefix, source, result_json, queried_at, expires_at)
                    VALUES (:h, :prefix, :source, :result, :now, :expires)
                    ON CONFLICT (url_hash) DO UPDATE SET source = EXCLUDED.source, result_json = EXCLUDED.result_json, queried_at = EXCLUDED.queried_at, expires_at = EXCLUDED.expires_at
                    """
                ),
                {
                    "h": h,
                    "prefix": url[:120],
                    "source": source,
                    "result": json.dumps(result),
                    "now": now,
                    "expires": now + _CACHE_TTL_SEC,
                },
            )
            db.commit()
    except Exception:
        pass


def enqueue_url_threat_intel(url: str) -> Dict[str, Any]:
    """Queue async URL intel lookup so request path can stay low-latency.

    Returns queue status; no network calls are performed inline except cache lookup.
    """
    u = str(url or "").strip()
    if not u:
        return {"queued": False, "reason": "empty_url"}
    try:
        ensure_safe_outbound_url(u)
    except Exception as exc:
        return {"queued": False, "reason": f"unsafe_url:{str(exc)[:120]}"}
    _ensure_tables()
    cached = _get_cached(u)
    if cached:
        return {"queued": False, "cache_hit": True, "malicious": bool(cached.get("malicious"))}
    h = _url_hash(u)
    with _INTEL_INFLIGHT_LOCK:
        if h in _INTEL_INFLIGHT:
            return {"queued": False, "inflight": True}
        _INTEL_INFLIGHT.add(h)

    def _job(target: str, key: str) -> None:
        try:
            check_url_threat_intel(target, use_cache=True)
        except Exception:
            pass
        finally:
            with _INTEL_INFLIGHT_LOCK:
                _INTEL_INFLIGHT.discard(key)

    try:
        _INTEL_EXECUTOR.submit(_job, u, h)
        return {"queued": True}
    except Exception as exc:
        with _INTEL_INFLIGHT_LOCK:
            _INTEL_INFLIGHT.discard(h)
        return {"queued": False, "reason": f"submit_failed:{str(exc)[:120]}"}


def _log_event(url: str, source: str, malicious: bool, detail: Dict[str, Any]) -> None:
    try:
        with db_session() as db:
            db.execute(
                text(
                    """
                    INSERT INTO threat_intel_events (id, url_prefix, source, malicious, detail_json, created_at)
                    VALUES (:id, :prefix, :source, :mal, :detail, :now)
                    """
                ),
                {
                    "id": f"ti-{uuid.uuid4().hex[:16]}",
                    "prefix": url[:120],
                    "source": source,
                    "mal": 1 if malicious else 0,
                    "detail": json.dumps(detail),
                    "now": int(time.time()),
                },
            )
            db.commit()
    except Exception:
        pass


def _check_urlhaus(url: str) -> Dict[str, Any]:
    """Check URL against URLhaus (abuse.ch) free API."""
    try:
        import urllib.request
        import urllib.parse

        body = urllib.parse.urlencode({"url": url}).encode("utf-8")
        req = urllib.request.Request(
            "https://urlhaus-api.abuse.ch/v1/url/",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        status = data.get("query_status", "")
        if status == "ok":
            threat = data.get("threat", "")
            tags = data.get("tags", []) or []
            return {
                "source": "urlhaus",
                "found": True,
                "malicious": True,
                "threat": threat,
                "tags": tags[:10],
                "date_added": data.get("date_added"),
            }
        return {"source": "urlhaus", "found": False, "malicious": False}
    except Exception as exc:
        return {"source": "urlhaus", "found": False, "malicious": False, "error": str(exc)[:200]}


def _check_virustotal(url: str) -> Dict[str, Any]:
    """Check URL against VirusTotal v3 API."""
    if not _VT_API_KEY:
        return {"source": "virustotal", "found": False, "malicious": False, "error": "no_api_key"}
    try:
        import urllib.request

        url_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        req = urllib.request.Request(
            f"https://www.virustotal.com/api/v3/urls/{url_id}",
            method="GET",
            headers={"x-apikey": _VT_API_KEY},
        )
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        stats = data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
        malicious_count = int(stats.get("malicious", 0))
        suspicious_count = int(stats.get("suspicious", 0))
        total = sum(stats.values()) if stats else 1
        detection_ratio = (malicious_count + suspicious_count) / max(total, 1)
        return {
            "source": "virustotal",
            "found": True,
            "malicious": detection_ratio > 0.1,
            "detection_ratio": round(detection_ratio, 3),
            "malicious_count": malicious_count,
            "suspicious_count": suspicious_count,
            "total_scanners": total,
        }
    except Exception as exc:
        return {"source": "virustotal", "found": False, "malicious": False, "error": str(exc)[:200]}


def _check_google_safe_browsing(url: str) -> Dict[str, Any]:
    """Check URL against Google Safe Browsing API v4."""
    if not _GSB_API_KEY:
        return {"source": "google_safe_browsing", "found": False, "malicious": False, "error": "no_api_key"}
    try:
        import urllib.request

        payload = json.dumps({
            "client": {"clientId": "shopsquire", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}],
            },
        }).encode("utf-8")
        api_url = f"https://safebrowsing.googleapis.com/v4/threatMatches:find?key={_GSB_API_KEY}"
        req = urllib.request.Request(
            api_url,
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT_SEC) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        matches = data.get("matches", [])
        if matches:
            threats = [m.get("threatType", "") for m in matches]
            return {
                "source": "google_safe_browsing",
                "found": True,
                "malicious": True,
                "threat_types": threats,
            }
        return {"source": "google_safe_browsing", "found": False, "malicious": False}
    except Exception as exc:
        return {"source": "google_safe_browsing", "found": False, "malicious": False, "error": str(exc)[:200]}


def check_url_threat_intel(
    url: str,
    *,
    use_cache: bool = True,
) -> Dict[str, Any]:
    """Check a URL against all available threat-intelligence sources.

    Returns combined result with per-source verdicts and an aggregate risk score.
    """
    _ensure_tables()
    u = str(url or "").strip()
    if not u:
        return {"url": "", "risk": 0.0, "sources": [], "malicious": False}

    # Mandatory SSRF protection for every outbound URL reputation lookup.
    try:
        ensure_safe_outbound_url(u)
    except Exception as exc:
        return {
            "url": u[:2048],
            "risk": 0.9,
            "sources": [],
            "malicious": True,
            "reasons": [f"unsafe_url:{str(exc)[:140]}"],
        }

    # Validate URL is parseable
    try:
        parsed = urlparse(u)
        if not parsed.scheme or not parsed.hostname:
            return {"url": u[:2048], "risk": 0.3, "sources": [], "malicious": False,
                    "reasons": ["unparseable_url"]}
    except Exception:
        return {"url": u[:2048], "risk": 0.3, "sources": [], "malicious": False,
                "reasons": ["parse_error"]}

    # Check cache
    if use_cache:
        cached = _get_cached(u)
        if cached:
            return cached

    # Query all available sources
    sources: List[Dict[str, Any]] = []
    sources.append(_check_urlhaus(u))
    sources.append(_check_virustotal(u))
    sources.append(_check_google_safe_browsing(u))

    # Aggregate
    any_malicious = any(s.get("malicious") for s in sources)
    sources_with_data = [s for s in sources if s.get("found")]
    malicious_count = sum(1 for s in sources if s.get("malicious"))
    total_checked = sum(1 for s in sources if not s.get("error"))

    # Risk scoring
    if malicious_count >= 2:
        risk = 0.95
    elif malicious_count == 1:
        risk = 0.7
    elif sources_with_data:
        risk = 0.05  # found but clean
    else:
        risk = 0.0  # no data available

    result = {
        "url": u[:2048],
        "risk": round(risk, 3),
        "malicious": any_malicious,
        "malicious_source_count": malicious_count,
        "total_sources_checked": total_checked,
        "sources": sources,
    }

    # Cache and log
    _store_cache(u, "combined", result)
    if any_malicious:
        _log_event(u, "combined", True, result)

    return result


def check_urls_batch(
    urls: List[str],
    *,
    max_urls: int = 10,
) -> List[Dict[str, Any]]:
    """Check multiple URLs against threat intelligence (bounded)."""
    results = []
    for url in (urls or [])[:max_urls]:
        results.append(check_url_threat_intel(url))
    return results
