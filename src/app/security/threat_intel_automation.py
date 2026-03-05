from __future__ import annotations

import csv
import io
import os
from typing import Any, Dict, List

import httpx

from src.app.security.threat_intel_store import upsert_indicator


def _norm_max_items(v: Any, default: int = 500) -> int:
    try:
        return max(1, min(int(v or default), 5000))
    except Exception:
        return default


def sync_cisa_kev(*, tenant_id: str | None = None, max_items: int = 2000) -> Dict[str, Any]:
    url = str(
        os.getenv(
            "CISA_KEV_JSON_URL",
            "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
        )
        or ""
    ).strip()
    if not url:
        return {"source": "cisa_kev", "synced": 0, "error": "url_not_configured"}
    lim = _norm_max_items(max_items, default=2000)
    synced = 0
    errors = 0
    try:
        resp = httpx.get(url, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
        vulns = data.get("vulnerabilities") if isinstance(data, dict) else []
        for item in (vulns or [])[:lim]:
            if not isinstance(item, dict):
                continue
            cve = str(item.get("cveID") or "").strip().upper()
            if not cve.startswith("CVE-"):
                continue
            ok = upsert_indicator(
                id=f"kev:{cve}",
                tenant_id=tenant_id,
                indicator_type="cve",
                indicator_value=cve,
                verdict="malicious",
                confidence=0.99,
                source="cisa_kev",
                notes=str(item.get("vulnerabilityName") or "")[:500],
            )
            if ok:
                synced += 1
            else:
                errors += 1
    except Exception as exc:
        return {"source": "cisa_kev", "synced": synced, "errors": errors, "error": str(exc)[:300]}
    return {"source": "cisa_kev", "synced": synced, "errors": errors}


def sync_urlhaus(*, tenant_id: str | None = None, max_items: int = 1500) -> Dict[str, Any]:
    url = str(os.getenv("URLHAUS_CSV_RECENT_URL", "https://urlhaus.abuse.ch/downloads/csv_recent/") or "").strip()
    if not url:
        return {"source": "urlhaus", "synced": 0, "error": "url_not_configured"}
    lim = _norm_max_items(max_items, default=1500)
    synced = 0
    errors = 0
    try:
        resp = httpx.get(url, timeout=20.0)
        resp.raise_for_status()
        lines = [ln for ln in resp.text.splitlines() if ln and not ln.startswith("#")]
        reader = csv.reader(io.StringIO("\n".join(lines)))
        for row in list(reader)[:lim]:
            if len(row) < 3:
                continue
            url_val = str(row[2] or "").strip()
            if not url_val:
                continue
            ioc_id = f"urlhaus:{abs(hash(url_val))}"
            ok = upsert_indicator(
                id=ioc_id,
                tenant_id=tenant_id,
                indicator_type="url",
                indicator_value=url_val,
                verdict="malicious",
                confidence=0.95,
                source="urlhaus",
                notes=(str(row[7]) if len(row) > 7 else "")[:500],
            )
            if ok:
                synced += 1
            else:
                errors += 1
    except Exception as exc:
        return {"source": "urlhaus", "synced": synced, "errors": errors, "error": str(exc)[:300]}
    return {"source": "urlhaus", "synced": synced, "errors": errors}


def sync_malwarebazaar(*, tenant_id: str | None = None, max_items: int = 1000) -> Dict[str, Any]:
    endpoint = str(os.getenv("MALWAREBAZAAR_API_URL", "https://mb-api.abuse.ch/api/v1/") or "").strip()
    if not endpoint:
        return {"source": "malwarebazaar", "synced": 0, "error": "url_not_configured"}
    lim = _norm_max_items(max_items, default=1000)
    synced = 0
    errors = 0
    try:
        resp = httpx.post(endpoint, data={"query": "get_recent", "selector": "time"}, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else []
        for item in (rows or [])[:lim]:
            if not isinstance(item, dict):
                continue
            sha256 = str(item.get("sha256_hash") or "").strip().lower()
            if len(sha256) != 64:
                continue
            family = str(item.get("signature") or item.get("file_type_mime") or "")
            ok = upsert_indicator(
                id=f"mbz:{sha256}",
                tenant_id=tenant_id,
                indicator_type="hash_sha256",
                indicator_value=sha256,
                verdict="malicious",
                confidence=0.97,
                source="malwarebazaar",
                notes=family[:500],
            )
            if ok:
                synced += 1
            else:
                errors += 1
    except Exception as exc:
        return {"source": "malwarebazaar", "synced": synced, "errors": errors, "error": str(exc)[:300]}
    return {"source": "malwarebazaar", "synced": synced, "errors": errors}


def sync_otx(*, tenant_id: str | None = None, max_items: int = 2000) -> Dict[str, Any]:
    """Pull recent threat indicators from AlienVault OTX (Open Threat Exchange).

    Requires OTX_API_KEY environment variable. Each "pulse" can contain
    indicators of type IPv4, domain, hostname, URL, and FileHash-SHA256.
    """
    api_key = str(os.getenv("OTX_API_KEY", "") or "").strip()
    if not api_key:
        return {"source": "otx", "synced": 0, "skipped": True, "reason": "OTX_API_KEY_not_configured"}
    base_url = str(os.getenv("OTX_API_URL", "https://otx.alienvault.com") or "").rstrip("/")
    endpoint = f"{base_url}/api/v1/pulses/subscribed"
    lim = _norm_max_items(max_items, default=2000)
    synced = 0
    errors = 0
    try:
        headers = {"X-OTX-API-KEY": api_key, "Content-Type": "application/json"}
        resp = httpx.get(endpoint, headers=headers, timeout=20.0, params={"limit": min(lim, 100)})
        resp.raise_for_status()
        data = resp.json()
        pulses = data.get("results") if isinstance(data, dict) else []
        for pulse in (pulses or [])[:lim]:
            if not isinstance(pulse, dict):
                continue
            pulse_id = str(pulse.get("id") or "").strip()
            pulse_name = str(pulse.get("name") or "")[:200]
            for ind in (pulse.get("indicators") or []):
                if not isinstance(ind, dict):
                    continue
                ind_type = str(ind.get("type") or "").lower()
                ind_value = str(ind.get("indicator") or "").strip()
                if not ind_value:
                    continue
                # Map OTX types to our indicator_type vocabulary
                type_map = {
                    "ipv4": "ip",
                    "ipv6": "ip",
                    "domain": "domain",
                    "hostname": "domain",
                    "url": "url",
                    "filehash-sha256": "hash_sha256",
                    "filehash-md5": "hash_md5",
                    "email": "email",
                }
                canonical_type = type_map.get(ind_type, ind_type)
                ioc_id = f"otx:{pulse_id}:{abs(hash(ind_value))}"
                ok = upsert_indicator(
                    id=ioc_id,
                    tenant_id=tenant_id,
                    indicator_type=canonical_type,
                    indicator_value=ind_value,
                    verdict="malicious",
                    confidence=0.9,
                    source="otx",
                    notes=f"pulse:{pulse_name}"[:500],
                )
                if ok:
                    synced += 1
                else:
                    errors += 1
                if synced + errors >= lim:
                    break
            if synced + errors >= lim:
                break
    except Exception as exc:
        return {"source": "otx", "synced": synced, "errors": errors, "error": str(exc)[:300]}
    return {"source": "otx", "synced": synced, "errors": errors}


def sync_all_automated_feeds(*, tenant_id: str | None = None) -> Dict[str, Any]:
    return {
        "kev": sync_cisa_kev(tenant_id=tenant_id),
        "urlhaus": sync_urlhaus(tenant_id=tenant_id),
        "malwarebazaar": sync_malwarebazaar(tenant_id=tenant_id),
        "otx": sync_otx(tenant_id=tenant_id),
    }
