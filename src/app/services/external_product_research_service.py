"""Safe external/web product research ("safe internet search").

Guardrails — ALL enforced here and unit-tested:
  1. disabled by default (the `enabled` flag must be explicitly True).
  2. PII scrubbed BEFORE egress (the injected `scrub` runs on the query first).
  3. domain allowlist — hits from non-allowlisted domains are dropped (defense in depth, even if a
     fetcher misbehaves).
  4. SKU-gate — a hit is `sold_here` only if its name/model maps to a real catalog SKU; otherwise
     `sku=None` + label "not sold by this store" (structurally un-cartable downstream).
  5. data-not-instructions — fetched text only populates display fields; it is never returned as an
     instruction and no tool/policy/LLM path consumes it as one.
  6. cache + freshness (optional Redis) with a per-item `fetched_ts`.

Returns a SEPARATE labeled result + its own SourceStatus. The caller attaches it to a dedicated
payload field and source-status list — it is NEVER merged into owned `results` or cart.

CORE / vertical-blind.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from src.app.services.commerce_source_status import SourceStatus

_SOURCE = "external_research"
_DOMAIN_RE = re.compile(r"^[a-z0-9.-]+$", re.IGNORECASE)


def _disabled() -> Dict[str, Any]:
    return {
        "status": "disabled",
        "items": [],
        "source_status": SourceStatus(source=_SOURCE, status="unavailable").to_dict(),
    }


def _domain_ok(domain: Any, allowlist: List[str]) -> bool:
    d = str(domain or "").strip().lower()
    if not d or not _DOMAIN_RE.match(d):
        return False
    for a in allowlist or []:
        a = str(a or "").strip().lower()
        if a and (d == a or d.endswith("." + a)):
            return True
    return False


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _map_sku(hit: Dict[str, Any], catalog_skus: List[str], catalog_names: Dict[str, str]) -> Optional[str]:
    hit_sku = str(hit.get("sku") or "").strip()
    if hit_sku and hit_sku in set(catalog_skus or []):
        return hit_sku
    hay = (_norm(hit.get("name") or hit.get("title")) + " " + _norm(hit.get("model"))).strip()
    if not hay:
        return None
    for sku, name in (catalog_names or {}).items():
        n = _norm(name)
        if n and (n in hay or hay in n):
            return str(sku)
    return None


def research(
    query: str,
    *,
    fetcher: Any,
    allowlist: List[str],
    catalog_skus: Optional[List[str]] = None,
    catalog_names: Optional[Dict[str, str]] = None,
    enabled: bool = False,
    scrub: Optional[Callable[[str], str]] = None,
    redis: Any = None,
    cache_namespace: str = "",
    timeout_s: float = 4.0,
    max_items: int = 8,
) -> Dict[str, Any]:
    """Run guarded external research. Returns {status, items, source_status}. Never raises."""
    if not enabled:
        return _disabled()
    scrub = scrub or (lambda x: x)
    scrubbed = scrub(str(query or ""))
    allow = [a for a in (allowlist or []) if str(a or "").strip()]
    t0 = time.perf_counter()

    # Namespace the cache by tenant/profile so verticals never see each other's web results.
    cache_key = "extres:" + hashlib.sha256(
        (str(cache_namespace) + "|" + scrubbed + "|" + ",".join(sorted(allow))).encode("utf-8")
    ).hexdigest()[:24]
    if redis is not None:
        with contextlib.suppress(Exception):
            raw = redis.get(cache_key)
            if raw:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8")
                cached = json.loads(raw)
                cached["status"] = "cached"
                return cached

    try:
        hits = fetcher.fetch(scrubbed, allowlist=list(allow), timeout_s=timeout_s) or []
    except Exception as exc:
        return {
            "status": "error",
            "items": [],
            "source_status": SourceStatus.errored(_SOURCE, str(exc), int((time.perf_counter() - t0) * 1000)).to_dict(),
        }

    names = catalog_names or {}
    skus = catalog_skus or []
    items: List[Dict[str, Any]] = []
    for h in hits[: max_items * 3]:
        if not isinstance(h, dict):
            continue
        if not _domain_ok(h.get("source_domain"), allow):  # allowlist defense in depth
            continue
        sku = _map_sku(h, skus, names)
        items.append({
            "title": str(h.get("title") or h.get("name") or "")[:200],
            "snippet": str(h.get("snippet") or "")[:400],
            "source_domain": str(h.get("source_domain") or "").lower(),
            "url": str(h.get("url") or "")[:500],
            "sku": sku,
            "sold_here": bool(sku),
            "label": None if sku else "not sold by this store",
            "fetched_ts": int(time.time()),
        })
        if len(items) >= max_items:
            break

    out = {
        "status": "ok" if items else "empty",
        "items": items,
        "source_status": SourceStatus.from_hits(_SOURCE, items, int((time.perf_counter() - t0) * 1000)).to_dict(),
    }
    if redis is not None:
        with contextlib.suppress(Exception):
            redis.setex(cache_key, 600, json.dumps(out))
    return out


def run_external_research_stage(
    *,
    query: str,
    results: Optional[List[Dict[str, Any]]] = None,
    flags: Optional[Dict[str, Any]] = None,
    scrub: Optional[Callable[[str], str]] = None,
    redis: Any = None,
    tenant_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Route wrapper for safe internet search. Resolves enabled (env EXTERNAL_RESEARCH_ENABLED >
    flag), picks the fetcher (SSRF-safe httpx adapter when EXTERNAL_RESEARCH_SEARCH_URL is set, else
    the inert NullFetcher), resolves the PER-PROFILE allowlist (cache namespaced by tenant+profile),
    SKU-gates against the owned results, and runs research(). Returns {items, source_status} when it
    ran, or None when disabled. Raises on internal error so the caller can trace it (matches the
    route's _trace_system_error)."""
    flags = flags or {}
    raw = os.getenv("EXTERNAL_RESEARCH_ENABLED")
    enabled = (
        str(raw).strip().lower() in ("1", "true", "yes")
        if raw is not None
        else bool(flags.get("EXTERNAL_RESEARCH_ENABLED", False))
    )
    if not enabled:
        return None

    # Real SSRF-safe httpx adapter ONLY when an operator-configured search endpoint exists; otherwise
    # the NullFetcher keeps external research inert (empty) even when the flag is on.
    if os.getenv("EXTERNAL_RESEARCH_SEARCH_URL"):
        from src.app.adapters.external_research_httpx import HttpxResearchFetcher as _fetcher
    else:
        from src.app.ports.external_product_research import NullFetcher as _fetcher
    from src.app.platform.store_profile import active_profile_id as _active_pid, profile_slot as _profile_slot

    # AGNOSTIC: allowlist comes from the ACTIVE profile, falling back to the global config.
    allow = _profile_slot("external_research_allowlist", default=None) or flags.get("EXTERNAL_RESEARCH_ALLOWLIST") or []
    res = research(
        query,
        fetcher=_fetcher(),
        allowlist=allow,
        catalog_skus=[str(r.get("sku") or "") for r in (results or []) if isinstance(r, dict)],
        catalog_names={
            str(r.get("sku")): str(r.get("name") or "")
            for r in (results or []) if isinstance(r, dict) and r.get("sku")
        },
        enabled=True,
        scrub=scrub,
        redis=redis,
        cache_namespace=f"{tenant_id or ''}:{_active_pid()}",
    )
    return {"items": res.get("items") or [], "source_status": res.get("source_status")}
