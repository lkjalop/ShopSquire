"""MISP / OpenCTI threat-feed integration.

Pulls IOCs from MISP (via REST) and/or OpenCTI (via GraphQL) and
persists them through the existing `threat_intel_store` module so that
the enrichment layer picks them up automatically.

ENV configuration
-----------------
MISP_URL            – Base URL of the MISP instance (e.g. https://misp.local)
MISP_API_KEY        – API key for MISP REST access
MISP_VERIFY_TLS     – "0" to disable TLS verification (default "1")
MISP_PULL_LIMIT     – Max events to pull per sync cycle (default 200)
OPENCTI_URL         – Base URL of OpenCTI (e.g. https://opencti.local)
OPENCTI_TOKEN       – Bearer token for OpenCTI API
OPENCTI_VERIFY_TLS  – "0" to disable TLS verification (default "1")
OPENCTI_PULL_LIMIT  – Max indicators per sync (default 500)
FEED_SYNC_TENANT_ID – Tenant scope for ingested IOCs (default None = global)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

from src.app.security.threat_intel_store import upsert_indicator

logger = logging.getLogger("shopsquire.misp_feed")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    return (os.getenv(key) or default).strip()


def _env_int(key: str, default: int) -> int:
    try:
        v = os.getenv(key)
        if v is None or str(v).strip() == "":
            return default
        return max(1, int(float(str(v).strip())))
    except Exception:
        return default


def _verify_tls(key: str) -> bool:
    return _env(key, "1") not in ("0", "false", "no")


def _deterministic_id(source: str, ioc_type: str, value: str) -> str:
    """Stable ID so upserts are idempotent."""
    return hashlib.sha256(f"{source}:{ioc_type}:{value}".encode("utf-8")).hexdigest()[:24]


_MISP_TYPE_MAP: Dict[str, str] = {
    "ip-src": "ip",
    "ip-dst": "ip",
    "domain": "domain",
    "hostname": "domain",
    "url": "url",
    "md5": "hash",
    "sha1": "hash",
    "sha256": "hash",
    "email-src": "email",
    "email-dst": "email",
    "filename": "filename",
    "filename|md5": "hash",
    "filename|sha256": "hash",
}

_OPENCTI_TYPE_MAP: Dict[str, str] = {
    "ipv4-addr": "ip",
    "ipv6-addr": "ip",
    "domain-name": "domain",
    "url": "url",
    "file": "hash",
    "email-addr": "email",
}


def _misp_verdict(event_threat_level: int | str | None) -> str:
    """Map MISP threat_level_id → local verdict string."""
    try:
        level = int(event_threat_level or 3)
    except (TypeError, ValueError):
        level = 3
    if level <= 1:
        return "malicious"
    if level == 2:
        return "suspicious"
    return "unknown"


# ---------------------------------------------------------------------------
# MISP pull
# ---------------------------------------------------------------------------

def pull_misp(
    *,
    tenant_id: str | None = None,
    since_timestamp: str | None = None,
) -> Dict[str, Any]:
    """Fetch recent events from MISP and ingest their attributes.

    Returns a summary dict with counts.
    """
    base_url = _env("MISP_URL")
    api_key = _env("MISP_API_KEY")
    if not base_url or not api_key:
        return {"status": "skipped", "reason": "MISP_URL or MISP_API_KEY not configured"}

    verify = _verify_tls("MISP_VERIFY_TLS")
    limit = _env_int("MISP_PULL_LIMIT", 200)
    tenant = tenant_id or _env("FEED_SYNC_TENANT_ID") or None

    search_body: Dict[str, Any] = {
        "returnFormat": "json",
        "limit": limit,
        "published": True,
    }
    if since_timestamp:
        search_body["timestamp"] = since_timestamp

    url = f"{base_url.rstrip('/')}/events/restSearch"
    headers = {
        "Authorization": api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    ingested = 0
    skipped = 0
    errors = 0
    try:
        resp = requests.post(url, json=search_body, headers=headers, verify=verify, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("MISP pull failed: %s", exc)
        return {"status": "error", "reason": str(exc), "ingested": 0}

    events = data.get("response") or []
    if isinstance(events, dict):
        events = [events]

    for wrapper in events:
        event = wrapper.get("Event") or wrapper
        threat_level = event.get("threat_level_id")
        event_info = str(event.get("info") or "")[:200]
        for attr in event.get("Attribute") or []:
            misp_type = str(attr.get("type") or "").lower()
            value = str(attr.get("value") or "").strip()
            mapped_type = _MISP_TYPE_MAP.get(misp_type)
            if not mapped_type or not value:
                skipped += 1
                continue
            ioc_id = _deterministic_id("misp", mapped_type, value)
            verdict = _misp_verdict(threat_level)
            confidence = 0.75 if verdict == "malicious" else 0.5
            ok = upsert_indicator(
                id=ioc_id,
                tenant_id=tenant,
                indicator_type=mapped_type,
                indicator_value=value,
                verdict=verdict,
                confidence=confidence,
                source="misp",
                notes=f"event: {event_info}",
            )
            if ok:
                ingested += 1
            else:
                errors += 1

    return {"status": "ok", "ingested": ingested, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# OpenCTI pull (GraphQL)
# ---------------------------------------------------------------------------

_OPENCTI_INDICATORS_QUERY = """
query($first: Int, $after: ID) {
  indicators(first: $first, after: $after, orderBy: created_at, orderMode: desc) {
    edges {
      node {
        id
        name
        pattern
        pattern_type
        x_opencti_main_observable_type
        x_opencti_score
        created_at
        objectLabel { value }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""


def _parse_stix_pattern(pattern: str | None) -> List[Dict[str, str]]:
    """Best-effort extraction of IOC type + value from a STIX-2 pattern string.

    e.g. "[domain-name:value = 'evil.com']" → [{"type": "domain", "value": "evil.com"}]
    """
    import re

    results: List[Dict[str, str]] = []
    if not pattern:
        return results
    for m in re.finditer(
        r"\[?\s*(\S+?):value\s*=\s*'([^']+)'",
        pattern,
    ):
        stix_type = m.group(1).strip().lower()
        val = m.group(2).strip()
        mapped = _OPENCTI_TYPE_MAP.get(stix_type)
        if mapped and val:
            results.append({"type": mapped, "value": val})
    return results


def pull_opencti(
    *,
    tenant_id: str | None = None,
) -> Dict[str, Any]:
    """Fetch indicators from OpenCTI via GraphQL and ingest them."""
    base_url = _env("OPENCTI_URL")
    token = _env("OPENCTI_TOKEN")
    if not base_url or not token:
        return {"status": "skipped", "reason": "OPENCTI_URL or OPENCTI_TOKEN not configured"}

    verify = _verify_tls("OPENCTI_VERIFY_TLS")
    limit = _env_int("OPENCTI_PULL_LIMIT", 500)
    tenant = tenant_id or _env("FEED_SYNC_TENANT_ID") or None

    gql_url = f"{base_url.rstrip('/')}/graphql"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    ingested = 0
    skipped = 0
    errors = 0
    after: Optional[str] = None
    fetched = 0

    while fetched < limit:
        page_size = min(50, limit - fetched)
        variables: Dict[str, Any] = {"first": page_size}
        if after:
            variables["after"] = after

        try:
            resp = requests.post(
                gql_url,
                json={"query": _OPENCTI_INDICATORS_QUERY, "variables": variables},
                headers=headers,
                verify=verify,
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            logger.warning("OpenCTI pull failed: %s", exc)
            return {"status": "error", "reason": str(exc), "ingested": ingested}

        edges = (body.get("data") or {}).get("indicators", {}).get("edges") or []
        page_info = (body.get("data") or {}).get("indicators", {}).get("pageInfo") or {}

        for edge in edges:
            node = edge.get("node") or {}
            score = int(node.get("x_opencti_score") or 50)
            pattern = node.get("pattern")
            parsed = _parse_stix_pattern(pattern)
            if not parsed:
                skipped += 1
                continue
            for ioc in parsed:
                ioc_id = _deterministic_id("opencti", ioc["type"], ioc["value"])
                verdict = "malicious" if score >= 70 else ("suspicious" if score >= 40 else "unknown")
                confidence = min(1.0, score / 100.0)
                ok = upsert_indicator(
                    id=ioc_id,
                    tenant_id=tenant,
                    indicator_type=ioc["type"],
                    indicator_value=ioc["value"],
                    verdict=verdict,
                    confidence=confidence,
                    source="opencti",
                    notes=str(node.get("name") or "")[:200],
                )
                if ok:
                    ingested += 1
                else:
                    errors += 1
            fetched += 1

        if not page_info.get("hasNextPage"):
            break
        after = page_info.get("endCursor")

    return {"status": "ok", "ingested": ingested, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Unified sync entry-point
# ---------------------------------------------------------------------------

def sync_all_feeds(*, tenant_id: str | None = None, since_timestamp: str | None = None) -> Dict[str, Any]:
    """Pull from all configured feeds and return a combined summary."""
    results: Dict[str, Any] = {}
    t0 = time.monotonic()

    results["misp"] = pull_misp(tenant_id=tenant_id, since_timestamp=since_timestamp)
    results["opencti"] = pull_opencti(tenant_id=tenant_id)

    results["elapsed_seconds"] = round(time.monotonic() - t0, 2)
    results["total_ingested"] = sum(
        int(v.get("ingested") or 0) for v in results.values() if isinstance(v, dict)
    )
    return results
