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


def sync_all_automated_feeds(*, tenant_id: str | None = None) -> Dict[str, Any]:
    return {
        "kev": sync_cisa_kev(tenant_id=tenant_id),
        "urlhaus": sync_urlhaus(tenant_id=tenant_id),
        "malwarebazaar": sync_malwarebazaar(tenant_id=tenant_id),
    }
