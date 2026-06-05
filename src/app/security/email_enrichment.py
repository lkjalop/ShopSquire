from __future__ import annotations

from typing import Any, Dict, List
import hashlib
import json
import os
import time
import logging

try:
    import httpx as _httpx
except Exception:
    _httpx = None  # type: ignore[assignment]

from src.app.security.threat_intel_store import resolve_indicator

logger = logging.getLogger("shopsquire.email_enrichment")

_CACHE: Dict[str, Dict[str, Any]] = {}


def _cache_get(key: str) -> Dict[str, Any] | None:
    item = _CACHE.get(key)
    if not item:
        return None
    if float(item.get("exp", 0)) < time.time():
        _CACHE.pop(key, None)
        return None
    return item.get("value") if isinstance(item.get("value"), dict) else None


def _cache_set(key: str, value: Dict[str, Any], ttl_s: int = 900) -> None:
    _CACHE[key] = {"exp": time.time() + int(max(60, ttl_s)), "value": value}


def _hash_key(ioc_type: str, value: str) -> str:
    return hashlib.sha256(f"{ioc_type}:{value}".encode("utf-8")).hexdigest()[:24]


def enrich_iocs(iocs: List[Dict[str, Any]], *, tenant_id: str | None = None) -> Dict[str, Any]:
    """Best-effort IOC enrichment with local cache and weighted confidence.

    This keeps remote calls optional and fast; callers can still rely on
    deterministic rule-first outcomes when enrichment is unavailable.
    """
    provider_weights = {"local": 0.9, "otx": 0.6, "vt": 0.72, "abusech": 0.66, "stix_taxii": 0.75}
    malicious_threshold = float(os.getenv("IOC_FUSION_MALICIOUS_THRESHOLD", "0.7") or 0.7)
    try:
        from src.app.security.threshold_tuning import get_runtime_thresholds

        rt = get_runtime_thresholds(tenant_id)
        if rt.get("ioc_fusion_malicious_threshold") is not None:
            malicious_threshold = float(rt.get("ioc_fusion_malicious_threshold"))
    except Exception:
        pass
    out_items: List[Dict[str, Any]] = []
    hits = 0
    cache_hits = 0
    contradictions = 0

    for i in (iocs or [])[:30]:
        ioc_type = str(i.get("type") or "")
        value = str(i.get("value") or "")
        if not ioc_type or not value:
            continue
        ck = _hash_key(ioc_type, value)
        cached = _cache_get(ck)
        if cached:
            out_items.append(cached)
            if cached.get("malicious"):
                hits += 1
            cache_hits += 1
            continue

        provenance: List[Dict[str, Any]] = []
        local_mal = bool(i.get("denylisted"))
        local_benign = bool(i.get("allowlisted"))
        local_conf = 0.95 if local_mal else (0.8 if local_benign else 0.1)
        provenance.append(
            {
                "source": "local",
                "malicious": local_mal,
                "benign": local_benign,
                "confidence": round(float(local_conf), 3),
                "cached": False,
            }
        )
        # Persistent threat-intel override (tenant first, then global).
        try:
            ti = resolve_indicator(tenant_id=tenant_id, indicator_type=ioc_type, indicator_value=value)
        except Exception:
            ti = None
        if ti:
            tverdict = str(ti.get("verdict") or "").lower()
            tconf = float(ti.get("confidence") or 0.8)
            provenance.append(
                {
                    "source": str(ti.get("source") or "threat_intel_db"),
                    "malicious": tverdict in ("deny", "malicious", "block"),
                    "benign": tverdict in ("allow", "benign"),
                    "confidence": round(max(0.0, min(1.0, tconf)), 3),
                    "cached": False,
                }
            )

        # Optional OTX probe (lightweight endpoint; best-effort).
        otx_key = os.getenv("OTX_API_KEY")
        if otx_key and ioc_type in ("domain", "url", "ip"):
            try:
                indicator = value
                kind = "domain" if ioc_type == "domain" else ("IPv4" if ioc_type == "ip" else "url")
                url = f"https://otx.alienvault.com/api/v1/indicators/{kind}/{indicator}/general"
                r = _httpx.get(url, headers={"X-OTX-API-KEY": otx_key}, timeout=3.0)
                if 200 <= int(r.status_code) < 300:
                    body = r.json()
                    pulse_info = body.get("pulse_info") or {}
                    count = int(len(pulse_info.get("pulses") or []))
                    otx_mal = bool(count > 0)
                    otx_conf = min(0.95, provider_weights["otx"] + min(count, 10) * 0.02) if otx_mal else 0.2
                    provenance.append(
                        {
                            "source": "otx",
                            "malicious": otx_mal,
                            "benign": not otx_mal,
                            "confidence": round(float(otx_conf), 3),
                            "cached": False,
                        }
                    )
            except Exception:
                pass

        pos_w = 0.0
        neg_w = 0.0
        has_pos = False
        has_neg = False
        for ev in provenance:
            src = str(ev.get("source") or "local")
            w = float(provider_weights.get(src, 0.5))
            c = float(ev.get("confidence") or 0.0)
            if bool(ev.get("malicious")):
                pos_w += w * c
                has_pos = True
            if bool(ev.get("benign")):
                neg_w += w * c
                has_neg = True
        denom = max(0.0001, pos_w + neg_w)
        base_score = pos_w / denom
        contradiction_penalty = 0.15 if (has_pos and has_neg) else 0.0
        if has_pos and has_neg:
            contradictions += 1
        fused_conf = max(0.0, min(1.0, float(base_score) - contradiction_penalty))
        malicious = bool(fused_conf >= malicious_threshold)
        top_source = max(provenance, key=lambda x: float(x.get("confidence") or 0.0)).get("source") if provenance else "local"
        enriched = {
            "type": ioc_type,
            "value_hash": hashlib.sha256(value.encode("utf-8")).hexdigest()[:24],
            "malicious": bool(malicious),
            "confidence": round(float(fused_conf), 3),
            "provider": top_source,
            "provenance": provenance,
            "contradiction_penalty": contradiction_penalty,
            "cache_ttl_seconds": int(os.getenv("IOC_ENRICH_CACHE_TTL_SEC", "900") or 900),
        }
        out_items.append(enriched)
        if enriched["malicious"]:
            hits += 1
        _cache_set(ck, enriched, ttl_s=int(os.getenv("IOC_ENRICH_CACHE_TTL_SEC", "900") or 900))

    return {
        "items": out_items,
        "malicious_hits": hits,
        "cache_hits": cache_hits,
        "contradictions": contradictions,
        "provider_weights": provider_weights,
        "fusion_threshold": malicious_threshold,
    }


def detonate_targets(urls: List[str], attachment_hashes: List[str]) -> Dict[str, Any]:
    """Best-effort private detonation adapter.

    Uses internal sandbox URL when configured. Falls back to local heuristic.
    """
    sandbox_url = os.getenv("PRIVATE_SANDBOX_URL")
    sandbox_token = os.getenv("PRIVATE_SANDBOX_TOKEN")

    findings: List[Dict[str, Any]] = []
    if sandbox_url:
        try:
            payload = {"urls": urls[:20], "attachment_hashes": attachment_hashes[:20]}
            headers = {"Content-Type": "application/json"}
            if sandbox_token:
                headers["Authorization"] = f"Bearer {sandbox_token}"
            r = _httpx.post(sandbox_url, headers=headers, content=json.dumps(payload).encode(), timeout=6.0)
            if 200 <= int(r.status_code) < 300:
                body = r.json() if "application/json" in (r.headers.get("content-type") or "") else {}
                return {
                    "provider": "private_sandbox",
                    "malicious": bool(body.get("malicious", False)),
                    "score": float(body.get("score", 0.0) or 0.0),
                    "findings": body.get("findings") or [],
                }
        except Exception as exc:
            logger.info("private sandbox detonation failed: %s", str(exc))

    # Local deterministic heuristic fallback.
    all_vals = " ".join((urls or []) + (attachment_hashes or [])).lower()
    suspicious = any(x in all_vals for x in ("login", "verify", "bank", "invoice", "reset-password"))
    if suspicious:
        findings.append({"signal": "suspicious_target_pattern", "reason": "contains high-risk lure keyword"})
    return {
        "provider": "local_heuristic",
        "malicious": bool(suspicious),
        "score": 0.6 if suspicious else 0.0,
        "findings": findings,
    }
