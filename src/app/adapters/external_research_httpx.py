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
import json
import os
import socket
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
    ):
        self._client = client
        self._template = search_url_template or os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or ""
        self._resolver = resolver or socket.getaddrinfo
        self._allow_private = _truthy(os.getenv("EXTERNAL_RESEARCH_ALLOW_PRIVATE")) if allow_private is None else bool(allow_private)
        self._ua = user_agent
        self._max_bytes = int(max_bytes)

    def fetch(self, scrubbed_query: str, *, allowlist: List[str], timeout_s: float = 4.0) -> List[Dict[str, Any]]:
        """Port entry point — never raises."""
        try:
            return self._fetch(scrubbed_query, allowlist or [], float(timeout_s))
        except Exception:
            return []

    def _fetch(self, scrubbed_query: str, allowlist: List[str], timeout_s: float) -> List[Dict[str, Any]]:
        if httpx is None or not self._template or not str(scrubbed_query).strip():
            return []
        url = self._template.replace("{query}", quote_plus(str(scrubbed_query)))
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return []
        if not _host_is_safe(parsed.hostname, resolver=self._resolver, allow_private=self._allow_private):
            return []

        client = self._client or httpx.Client(
            timeout=timeout_s, follow_redirects=False, headers={"User-Agent": self._ua}
        )
        owns = self._client is None
        try:
            resp = client.get(url, timeout=timeout_s)
            if not (200 <= resp.status_code < 300):  # 3xx (un-followed redirect) / 4xx / 5xx → no data
                return []
            data = json.loads(resp.text[: self._max_bytes])
        finally:
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
            })
        return out
