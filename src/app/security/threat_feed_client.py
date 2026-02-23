"""MISP / OpenCTI threat feed integration (P2).

Provides a client for ingesting external IOC (Indicators of Compromise) feeds:
- MISP (Malware Information Sharing Platform) REST API
- OpenCTI GraphQL API
- STIX/TAXII 2.1 feed polling

IOCs are ingested into the local ``threat_intel_indicators`` table
(see ``threat_intel_store.py``) so they participate in email/CV enrichment.

Usage:
    feed = ThreatFeedClient()
    await feed.sync_misp()           # pull from MISP
    await feed.sync_opencti()        # pull from OpenCTI
    await feed.sync_taxii(url=...)   # pull from TAXII server
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from src.app.security.threat_intel_store import upsert_indicator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MISP_URL = os.getenv("MISP_URL", "").strip()
MISP_API_KEY = os.getenv("MISP_API_KEY", "").strip()
MISP_VERIFY_SSL = os.getenv("MISP_VERIFY_SSL", "1").strip().lower() in ("1", "true", "yes")

OPENCTI_URL = os.getenv("OPENCTI_URL", "").strip()
OPENCTI_TOKEN = os.getenv("OPENCTI_TOKEN", "").strip()

TAXII_URL = os.getenv("TAXII_FEED_URL", "").strip()
TAXII_USERNAME = os.getenv("TAXII_USERNAME", "").strip()
TAXII_PASSWORD = os.getenv("TAXII_PASSWORD", "").strip()

# Sync interval and limits
SYNC_INTERVAL_SEC = int(os.getenv("THREAT_FEED_SYNC_INTERVAL_SEC", "3600"))
MAX_INDICATORS_PER_SYNC = int(os.getenv("THREAT_FEED_MAX_PER_SYNC", "5000"))

_last_sync: Dict[str, float] = {}


def _should_sync(feed_name: str) -> bool:
    last = _last_sync.get(feed_name, 0.0)
    return (time.time() - last) >= SYNC_INTERVAL_SEC


def _mark_synced(feed_name: str) -> None:
    _last_sync[feed_name] = time.time()


def _ioc_id(source: str, ioc_type: str, value: str) -> str:
    raw = f"{source}:{ioc_type}:{value}"
    return f"ti-{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


# ---------------------------------------------------------------------------
# MISP integration
# ---------------------------------------------------------------------------

def _misp_type_to_local(misp_type: str) -> str | None:
    """Map MISP attribute types to local indicator types."""
    mapping = {
        "ip-src": "ip",
        "ip-dst": "ip",
        "domain": "domain",
        "hostname": "domain",
        "url": "url",
        "md5": "hash_md5",
        "sha1": "hash_sha1",
        "sha256": "hash_sha256",
        "email-src": "email",
        "email-dst": "email",
        "filename": "filename",
        "filename|sha256": "hash_sha256",
    }
    return mapping.get(misp_type)


def sync_misp(
    *,
    tenant_id: str | None = None,
    url: str | None = None,
    api_key: str | None = None,
    days_back: int = 7,
) -> Dict[str, Any]:
    """Pull recent IOCs from a MISP instance and upsert into local store.

    Returns summary of synced indicators.
    """
    misp_url = (url or MISP_URL).rstrip("/")
    key = api_key or MISP_API_KEY
    if not misp_url or not key:
        return {"synced": 0, "error": "MISP_URL or MISP_API_KEY not configured"}

    if not _should_sync("misp"):
        return {"synced": 0, "skipped": "within_sync_interval"}

    try:
        import httpx
    except ImportError:
        return {"synced": 0, "error": "httpx not installed"}

    synced = 0
    errors = 0
    try:
        timestamp = int(time.time()) - (days_back * 86400)
        resp = httpx.post(
            f"{misp_url}/attributes/restSearch",
            headers={
                "Authorization": key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "timestamp": str(timestamp),
                "limit": MAX_INDICATORS_PER_SYNC,
                "to_ids": True,
                "enforceWarninglist": True,
            },
            verify=MISP_VERIFY_SSL,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        attributes = (data.get("response") or {}).get("Attribute") or []
        for attr in attributes[:MAX_INDICATORS_PER_SYNC]:
            misp_type = str(attr.get("type") or "")
            local_type = _misp_type_to_local(misp_type)
            if not local_type:
                continue
            value = str(attr.get("value") or "").strip()
            if not value:
                continue
            ioc_id = _ioc_id("misp", local_type, value)
            ok = upsert_indicator(
                id=ioc_id,
                tenant_id=tenant_id,
                indicator_type=local_type,
                indicator_value=value,
                verdict="malicious",
                confidence=float(attr.get("confidence", 0.85) or 0.85) / 100.0
                if float(attr.get("confidence", 85) or 85) > 1.0
                else float(attr.get("confidence", 0.85) or 0.85),
                source=f"misp:{attr.get('event_id', 'unknown')}",
                notes=str(attr.get("comment") or "")[:500],
            )
            if ok:
                synced += 1
            else:
                errors += 1
        _mark_synced("misp")
    except Exception as exc:
        logger.warning("MISP sync failed: %s", exc)
        return {"synced": synced, "errors": errors, "error": str(exc)[:300]}

    return {"synced": synced, "errors": errors, "source": "misp"}


# ---------------------------------------------------------------------------
# OpenCTI integration
# ---------------------------------------------------------------------------

_OPENCTI_QUERY = """
query IndicatorsQuery($after: DateTime, $first: Int) {
  indicators(
    orderBy: created_at
    orderMode: desc
    filters: {
      mode: and
      filters: [{ key: "created_at", values: [$after], operator: gte }]
      filterGroups: []
    }
    first: $first
  ) {
    edges {
      node {
        id
        name
        pattern
        pattern_type
        x_opencti_score
        created_at
        objectLabel { value }
      }
    }
  }
}
"""


def _parse_stix_pattern(pattern: str) -> tuple[str | None, str | None]:
    """Extract type and value from a STIX indicator pattern like [ipv4-addr:value = '1.2.3.4']."""
    import re
    m = re.search(r"\[(\S+):value\s*=\s*'([^']+)'\]", pattern or "")
    if not m:
        return None, None
    stix_type = m.group(1)
    value = m.group(2)
    type_map = {
        "ipv4-addr": "ip",
        "ipv6-addr": "ip",
        "domain-name": "domain",
        "url": "url",
        "file": "hash_sha256",
        "email-addr": "email",
    }
    return type_map.get(stix_type), value


def sync_opencti(
    *,
    tenant_id: str | None = None,
    url: str | None = None,
    token: str | None = None,
    days_back: int = 7,
) -> Dict[str, Any]:
    """Pull recent IOCs from OpenCTI GraphQL API."""
    cti_url = (url or OPENCTI_URL).rstrip("/")
    tok = token or OPENCTI_TOKEN
    if not cti_url or not tok:
        return {"synced": 0, "error": "OPENCTI_URL or OPENCTI_TOKEN not configured"}

    if not _should_sync("opencti"):
        return {"synced": 0, "skipped": "within_sync_interval"}

    try:
        import httpx
    except ImportError:
        return {"synced": 0, "error": "httpx not installed"}

    from datetime import datetime, timedelta
    after = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

    synced = 0
    errors = 0
    try:
        resp = httpx.post(
            f"{cti_url}/graphql",
            headers={
                "Authorization": f"Bearer {tok}",
                "Content-Type": "application/json",
            },
            json={
                "query": _OPENCTI_QUERY,
                "variables": {"after": after, "first": MAX_INDICATORS_PER_SYNC},
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        edges = ((data.get("data") or {}).get("indicators") or {}).get("edges") or []
        for edge in edges[:MAX_INDICATORS_PER_SYNC]:
            node = edge.get("node") or {}
            pattern = str(node.get("pattern") or "")
            local_type, value = _parse_stix_pattern(pattern)
            if not local_type or not value:
                continue
            score = float(node.get("x_opencti_score") or 50) / 100.0
            ioc_id = _ioc_id("opencti", local_type, value)
            ok = upsert_indicator(
                id=ioc_id,
                tenant_id=tenant_id,
                indicator_type=local_type,
                indicator_value=value,
                verdict="malicious" if score >= 0.6 else "suspicious",
                confidence=min(1.0, max(0.0, score)),
                source=f"opencti:{node.get('id', 'unknown')}",
                notes=str(node.get("name") or "")[:500],
            )
            if ok:
                synced += 1
            else:
                errors += 1
        _mark_synced("opencti")
    except Exception as exc:
        logger.warning("OpenCTI sync failed: %s", exc)
        return {"synced": synced, "errors": errors, "error": str(exc)[:300]}

    return {"synced": synced, "errors": errors, "source": "opencti"}


# ---------------------------------------------------------------------------
# STIX/TAXII 2.1 polling
# ---------------------------------------------------------------------------

def sync_taxii(
    *,
    tenant_id: str | None = None,
    url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    collection_id: str | None = None,
) -> Dict[str, Any]:
    """Poll a TAXII 2.1 server for STIX indicator bundles."""
    taxii_url = (url or TAXII_URL).rstrip("/")
    user = username or TAXII_USERNAME
    pwd = password or TAXII_PASSWORD
    if not taxii_url:
        return {"synced": 0, "error": "TAXII_FEED_URL not configured"}

    if not _should_sync("taxii"):
        return {"synced": 0, "skipped": "within_sync_interval"}

    try:
        import httpx
    except ImportError:
        return {"synced": 0, "error": "httpx not installed"}

    synced = 0
    errors = 0
    try:
        coll = collection_id or "default"
        endpoint = f"{taxii_url}/collections/{coll}/objects/"
        auth = (user, pwd) if user and pwd else None
        resp = httpx.get(
            endpoint,
            headers={"Accept": "application/taxii+json;version=2.1"},
            auth=auth,
            timeout=30.0,
        )
        resp.raise_for_status()
        bundle = resp.json()
        objects = bundle.get("objects") or []
        for obj in objects[:MAX_INDICATORS_PER_SYNC]:
            if obj.get("type") != "indicator":
                continue
            pattern = str(obj.get("pattern") or "")
            local_type, value = _parse_stix_pattern(pattern)
            if not local_type or not value:
                continue
            confidence = float(obj.get("confidence", 75) or 75) / 100.0
            ioc_id = _ioc_id("taxii", local_type, value)
            ok = upsert_indicator(
                id=ioc_id,
                tenant_id=tenant_id,
                indicator_type=local_type,
                indicator_value=value,
                verdict="malicious" if confidence >= 0.6 else "suspicious",
                confidence=min(1.0, max(0.0, confidence)),
                source=f"taxii:{obj.get('id', 'unknown')}",
                notes=str(obj.get("name") or obj.get("description") or "")[:500],
            )
            if ok:
                synced += 1
            else:
                errors += 1
        _mark_synced("taxii")
    except Exception as exc:
        logger.warning("TAXII sync failed: %s", exc)
        return {"synced": synced, "errors": errors, "error": str(exc)[:300]}

    return {"synced": synced, "errors": errors, "source": "taxii"}


# ---------------------------------------------------------------------------
# Convenience: sync all configured feeds
# ---------------------------------------------------------------------------

def sync_all_feeds(*, tenant_id: str | None = None) -> Dict[str, Any]:
    """Sync all configured threat feeds (MISP, OpenCTI, TAXII)."""
    results: Dict[str, Any] = {}
    if MISP_URL and MISP_API_KEY:
        results["misp"] = sync_misp(tenant_id=tenant_id)
    if OPENCTI_URL and OPENCTI_TOKEN:
        results["opencti"] = sync_opencti(tenant_id=tenant_id)
    if TAXII_URL:
        results["taxii"] = sync_taxii(tenant_id=tenant_id)
    if not results:
        results["status"] = "no_feeds_configured"
    return results
