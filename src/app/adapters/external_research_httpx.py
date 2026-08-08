"""HttpxResearchFetcher — the REAL ExternalResearchFetcher binding (Track 5).

Implements the ExternalResearchFetcher port over httpx with SSRF defenses, so the guardrailed
external_product_research_service can actually reach the web in a networked deployment while staying
safe by construction:

  * ONE outbound request, to an OPERATOR-CONFIGURED search endpoint (EXTERNAL_RESEARCH_SEARCH_URL,
    a `{query}` template — e.g. a self-hosted SearXNG). The query only fills the URL-encoded
    `{query}` slot; it can NEVER change the host/scheme. Result URLs are returned as DATA and are
    NOT fetched, so the SSRF surface is exactly that one configured host.
  * SSRF guard on the endpoint host: scheme must be http/https; the host is DNS-resolved and any
    private / loopback / link-local / reserved / multicast / unspecified address is refused (unless
    EXTERNAL_RESEARCH_ALLOW_PRIVATE=1 for a localhost dev endpoint).
  * redirects are NOT followed (a 3xx to an internal host yields no data).
  * response is size-bounded and only 2xx JSON is parsed.
  * result domains are filtered against the caller's allowlist (defense in depth — the service
    filters again).
  * NEVER raises — every failure path returns [] (fail-open-to-empty, per the port contract).

Injectable for hermetic tests: pass `client=httpx.Client(transport=httpx.MockTransport(...))` and a
fake `resolver`. CORE / vertical-blind.
"""
from __future__ import annotations

import ipaddress
import hashlib
import json
import os
import socket
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote_plus, urlparse

try:
    import httpx
except Exception:  # pragma: no cover - httpx is a hard dep; guard keeps import-time safe
    httpx = None  # type: ignore

_DEFAULT_UA = "ShopSquire-Research/1.0 (+safe-research)"
_DEFAULT_MAX_BYTES = 512 * 1024


def _truthy(v: Optional[str]) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _host_is_safe(host: str, *, resolver: Callable[..., Any], allow_private: bool = False) -> bool:
    """True only if the host resolves exclusively to public, routable addresses. Fail-closed."""
    if not host:
        return False
    if allow_private:
        return True
    try:
        infos = resolver(host, None)
    except Exception:
        return False
    ips = [info[4][0] for info in (infos or []) if info and len(info) >= 5 and info[4]]
    if not ips:
        return False
    for ip in ips:
        try:
            addr = ipaddress.ip_address(str(ip).split("%")[0])  # strip any zone id
        except ValueError:
            return False
        if (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved
                or addr.is_multicast or addr.is_unspecified):
            return False
    return True


def _domain_allowed(domain: str, allowlist: List[str]) -> bool:
    d = (domain or "").strip().lower()
    if not d:
        return False
    for a in allowlist or []:
        a = str(a or "").strip().lower()
        if a and (d == a or d.endswith("." + a)):
            return True
    return False


class HttpxResearchFetcher:
    """Real fetcher. Inert (returns []) until EXTERNAL_RESEARCH_SEARCH_URL is configured."""

    def __init__(
        self,
        *,
        client: Optional[Any] = None,
        search_url_template: Optional[str] = None,
        resolver: Optional[Callable[..., Any]] = None,
        allow_private: Optional[bool] = None,
        user_agent: str = _DEFAULT_UA,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        request_headers: Optional[Dict[str, str]] = None,
    ):
        self._client = client
        self._template = search_url_template or os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or ""
        self._resolver = resolver or socket.getaddrinfo
        self._allow_private = _truthy(os.getenv("EXTERNAL_RESEARCH_ALLOW_PRIVATE")) if allow_private is None else bool(allow_private)
        self._ua = user_agent
        self._max_bytes = int(max_bytes)
        # Headers are transport configuration only. They are never copied into result rows or
        # evidence traces, so connector credentials cannot leak into recommendation payloads.
        self._request_headers = {
            str(key): str(value)
            for key, value in (request_headers or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self.last_receipt: Dict[str, Any] = {
            "provider_capability": "WEB_DISCOVERY",
            "provider_id": "searxng_compatible_discovery",
            "fixture": False,
            "network_execution": False,
            "execution_status": "not_dispatched",
            "external_call_dispatched": False,
        }

    def fetch(
        self, scrubbed_query: str, *, allowlist: List[str], timeout_s: float = 4.0,
        cancellation: Any = None,
    ) -> List[Dict[str, Any]]:
        """Port entry point — never raises."""
        try:
            return self._fetch(
                scrubbed_query, allowlist or [], float(timeout_s), cancellation=cancellation,
            )
        except Exception:
            return []

    def _fetch(
        self, scrubbed_query: str, allowlist: List[str], timeout_s: float,
        *, cancellation: Any = None,
    ) -> List[Dict[str, Any]]:
        if httpx is None or not self._template or not str(scrubbed_query).strip():
            return []
        if bool(getattr(cancellation, "cancelled", False)):
            return []
        url = self._template.replace("{query}", quote_plus(str(scrubbed_query)))
        parsed = urlparse(url)
        self.last_receipt = {
            "provider_capability": "WEB_DISCOVERY",
            "provider_id": "searxng_compatible_discovery",
            "provider_endpoint_host": parsed.hostname,
            "query_hash": hashlib.sha256(str(scrubbed_query).encode("utf-8")).hexdigest()[:16],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "fixture": False,
            "network_execution": False,
            "cache_status": "miss",
            "billing_class": "unknown",
            "execution_status": "not_dispatched",
            "external_call_dispatched": False,
        }
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return []
        if not _host_is_safe(parsed.hostname, resolver=self._resolver, allow_private=self._allow_private):
            return []

        client = self._client or httpx.Client(
            timeout=timeout_s, follow_redirects=False, headers={"User-Agent": self._ua}
        )
        owns = self._client is None
        watch_done = threading.Event()
        cancel_event = getattr(cancellation, "event", None)
        if owns and cancel_event is not None:
            def _cancel_transport() -> None:
                if cancel_event.wait(timeout=max(0.0, timeout_s)) and not watch_done.is_set():
                    try:
                        client.close()
                    except Exception:
                        pass

            threading.Thread(
                target=_cancel_transport, name="external-research-cancel", daemon=True,
            ).start()
        try:
            resp = client.get(url, timeout=timeout_s, headers=self._request_headers or None)
            raw_body = bytes(resp.content)
            completed_at = datetime.now(timezone.utc).isoformat()
            self.last_receipt.update({
                "network_execution": True,
                "external_call_dispatched": True,
                "http_status": int(resp.status_code),
                "completed_at": completed_at,
                "observed_at": completed_at,
                "response_body_hash": hashlib.sha256(raw_body[: self._max_bytes]).hexdigest(),
                "response_bytes": len(raw_body),
                "execution_status": (
                    "completed" if 200 <= resp.status_code < 300 else "failed"
                ),
            })
            if not (200 <= resp.status_code < 300):  # 3xx (un-followed redirect) / 4xx / 5xx → no data
                return []
            data = json.loads(resp.text[: self._max_bytes])
        except Exception as exc:
            self.last_receipt.update({
                "network_execution": True,
                "external_call_dispatched": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "execution_status": "failed",
                "error": f"discovery_transport_error:{type(exc).__name__}",
            })
            raise
        finally:
            watch_done.set()
            if owns:
                try:
                    client.close()
                except Exception:
                    pass

        results = data.get("results") if isinstance(data, dict) else data
        if not isinstance(results, list):
            return []
        out: List[Dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            u = str(r.get("url") or "")
            dom = (urlparse(u).hostname or "").lower()
            if not _domain_allowed(dom, allowlist):  # adapter-side allowlist (defense in depth)
                continue
            out.append({
                "title": str(r.get("title") or r.get("name") or "")[:200],
                "snippet": str(r.get("snippet") or r.get("content") or r.get("description") or "")[:400],
                "url": u[:500],
                "source_domain": dom,
                # The service layer applies the bounded typed allowlist and strips
                # fetched authority/status fields. The adapter only transports the
                # connector's structured candidates alongside the source record.
                "claim_candidates": list(r.get("claim_candidates") or [])[:16]
                if isinstance(r.get("claim_candidates"), list) else [],
            })
        return out
