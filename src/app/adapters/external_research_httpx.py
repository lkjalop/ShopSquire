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

import asyncio
import ipaddress
import hashlib
import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import parse_qs, parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from src.app.services.discovery_engine_reliability import (
    DEFAULT_DISCOVERY_ENGINE_RELIABILITY,
    DiscoveryEngineReliability,
)

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


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(str(host).split("%")[0])
        return True
    except ValueError:
        return False


def _engine_failure_rows(value: Any) -> List[Dict[str, str]]:
    """Normalize SearXNG's list/tuple engine failures for a UI-safe receipt."""

    rows: List[Dict[str, str]] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, (list, tuple)) and item:
            engine = str(item[0] or "unknown")[:80]
            reason = str(item[1] if len(item) > 1 else "unresponsive")[:160]
        elif isinstance(item, dict):
            engine = str(item.get("engine") or item.get("name") or "unknown")[:80]
            reason = str(item.get("reason") or item.get("error") or "unresponsive")[:160]
        else:
            continue
        rows.append({"engine": engine, "reason": reason})
    return rows


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
        engine_reliability: Optional[DiscoveryEngineReliability] = None,
    ):
        self._client = client
        self._template = search_url_template or os.getenv("EXTERNAL_RESEARCH_SEARCH_URL") or ""
        self._resolver = resolver or socket.getaddrinfo
        self._allow_private = _truthy(os.getenv("EXTERNAL_RESEARCH_ALLOW_PRIVATE")) if allow_private is None else bool(allow_private)
        self._ua = user_agent
        self._max_bytes = int(max_bytes)
        self._engine_reliability = engine_reliability or DEFAULT_DISCOVERY_ENGINE_RELIABILITY
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
        cancellation: Any = None, discovery_candidates_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Port entry point — never raises."""
        try:
            return self._fetch(
                scrubbed_query, allowlist or [], float(timeout_s), cancellation=cancellation,
                discovery_candidates_only=discovery_candidates_only,
            )
        except Exception:
            return []

    def _fetch(
        self, scrubbed_query: str, allowlist: List[str], timeout_s: float,
        *, cancellation: Any = None, discovery_candidates_only: bool = False,
    ) -> List[Dict[str, Any]]:
        if httpx is None or not self._template or not str(scrubbed_query).strip():
            return []
        if bool(getattr(cancellation, "cancelled", False)):
            return []
        url = self._template.replace("{query}", quote_plus(str(scrubbed_query)))
        parsed = urlparse(url)
        endpoint = str(parsed.hostname or "")
        reliability_before = self._engine_reliability.snapshots(endpoint)
        suppressed_before = [row["engine"] for row in reliability_before if row["suppressed"]]
        if suppressed_before and not parse_qs(parsed.query).get("engines"):
            recommended = self._engine_reliability.recommended_engines(endpoint)
            query_items = parse_qsl(parsed.query, keep_blank_values=True)
            query_items.append(("engines", ",".join(recommended)))
            parsed = parsed._replace(query=urlencode(query_items))
            url = urlunparse(parsed)
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
            request_started = time.perf_counter()
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
        configured_engines = [
            value.strip() for value in parse_qs(parsed.query).get("engines", [""])[0].split(",")
            if value.strip()
        ]
        engine_failures = _engine_failure_rows(
            data.get("unresponsive_engines") if isinstance(data, dict) else None
        )
        responded_engines: set[str] = set()
        out: List[Dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            result_engines = r.get("engines") if isinstance(r.get("engines"), list) else []
            for engine in [r.get("engine"), *result_engines]:
                if str(engine or "").strip():
                    responded_engines.add(str(engine).strip())
            u = str(r.get("url") or "")
            dom = (urlparse(u).hostname or "").lower()
            parsed_result = urlparse(u)
            is_public_candidate = bool(
                parsed_result.scheme == "https" and parsed_result.hostname
                and not _is_ip_literal(parsed_result.hostname)
            )
            if not _domain_allowed(dom, allowlist) and not (
                discovery_candidates_only and is_public_candidate
            ):
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
        degradation_reasons: list[str] = []
        failure_text = " ".join(row["reason"].lower() for row in engine_failures)
        if "captcha" in failure_text:
            degradation_reasons.append("engines_captcha")
        if "too many requests" in failure_text or "rate" in failure_text:
            degradation_reasons.append("engines_rate_limited")
        if engine_failures and not degradation_reasons:
            degradation_reasons.append("engines_unresponsive")
        if not out:
            degradation_reasons.append("zero_allowlisted_results")
        self.last_receipt.update({
            "raw_result_count": len(results),
            "result_count": len(results),
            "allowlisted_result_count": len(out),
            "engines_queried": configured_engines,
            "engines_responded": sorted(responded_engines),
            "engine_failures": engine_failures,
            "degradation_reasons": degradation_reasons,
            "provider_status": "degraded" if degradation_reasons else "completed",
        })
        request_latency_ms = round((time.perf_counter() - request_started) * 1000, 3)
        self._engine_reliability.record(
            endpoint=endpoint, receipt=self.last_receipt, latency_ms=request_latency_ms,
        )
        reliability_after = self._engine_reliability.snapshots(endpoint)
        self.last_receipt.update({
            "request_latency_ms": request_latency_ms,
            "engine_reliability": reliability_after,
            "suppressed_engines": [
                row["engine"] for row in reliability_after if row["suppressed"]
            ],
        })
        return out


class AsyncHttpxResearchFetcher(HttpxResearchFetcher):
    """Async SearXNG transport whose socket work dies with the request task.

    The projection deliberately delegates to the existing bounded parser so
    sync and async callers cannot acquire different authority semantics.
    """

    def __init__(self, *, client: Any | None = None, **kwargs: Any) -> None:
        super().__init__(client=None, **kwargs)
        self._async_client = client

    async def fetch_async(
        self, scrubbed_query: str, *, allowlist: List[str], timeout_s: float = 4.0,
        discovery_candidates_only: bool = False,
    ) -> List[Dict[str, Any]]:
        try:
            return await self._fetch_async(
                scrubbed_query, allowlist or [], float(timeout_s),
                discovery_candidates_only=discovery_candidates_only,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            return []

    async def _fetch_async(
        self, scrubbed_query: str, allowlist: List[str], timeout_s: float,
        *, discovery_candidates_only: bool,
    ) -> List[Dict[str, Any]]:
        if httpx is None or not self._template or not str(scrubbed_query).strip():
            return []
        url = self._template.replace("{query}", quote_plus(str(scrubbed_query)))
        parsed = urlparse(url)
        endpoint = str(parsed.hostname or "")
        reliability_before = self._engine_reliability.snapshots(endpoint)
        suppressed_before = [row["engine"] for row in reliability_before if row["suppressed"]]
        if suppressed_before and not parse_qs(parsed.query).get("engines"):
            recommended = self._engine_reliability.recommended_engines(endpoint)
            query_items = parse_qsl(parsed.query, keep_blank_values=True)
            query_items.append(("engines", ",".join(recommended)))
            parsed = parsed._replace(query=urlencode(query_items))
            url = urlunparse(parsed)
        self.last_receipt = {
            "provider_capability": "WEB_DISCOVERY",
            "provider_id": "searxng_compatible_discovery",
            "provider_endpoint_host": parsed.hostname,
            "query_hash": hashlib.sha256(str(scrubbed_query).encode("utf-8")).hexdigest()[:16],
            "started_at": datetime.now(timezone.utc).isoformat(), "fixture": False,
            "network_execution": False, "cache_status": "miss", "billing_class": "free",
            "execution_status": "not_dispatched", "external_call_dispatched": False,
        }
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return []
        if not _host_is_safe(
            parsed.hostname, resolver=self._resolver, allow_private=self._allow_private,
        ):
            return []
        client = self._async_client or httpx.AsyncClient(
            timeout=timeout_s, follow_redirects=False, headers={"User-Agent": self._ua},
        )
        owns = self._async_client is None
        request_started = time.perf_counter()
        try:
            async with client.stream(
                "GET", url, timeout=timeout_s, headers=self._request_headers or None,
            ) as response:
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        self.last_receipt.update({
                            "network_execution": True, "external_call_dispatched": True,
                            "http_status": int(response.status_code),
                            "execution_status": "failed", "error": "discovery_body_too_large",
                        })
                        return []
                    chunks.append(chunk)
                raw_body = b"".join(chunks)
                status_code = int(response.status_code)
            completed_at = datetime.now(timezone.utc).isoformat()
            self.last_receipt.update({
                "network_execution": True, "external_call_dispatched": True,
                "http_status": status_code, "completed_at": completed_at,
                "observed_at": completed_at,
                "response_body_hash": hashlib.sha256(raw_body).hexdigest(),
                "response_bytes": len(raw_body),
                "execution_status": "completed" if 200 <= status_code < 300 else "failed",
            })
            if not 200 <= status_code < 300:
                return []
            data = json.loads(raw_body.decode("utf-8"))
            return self._project_results(
                data=data, parsed=parsed, endpoint=endpoint, allowlist=allowlist,
                discovery_candidates_only=discovery_candidates_only,
                request_started=request_started,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_receipt.update({
                "network_execution": True, "external_call_dispatched": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "execution_status": "failed",
                "error": f"discovery_transport_error:{type(exc).__name__}",
            })
            raise
        finally:
            if owns:
                await client.aclose()

    def _project_results(
        self, *, data: Any, parsed: Any, endpoint: str, allowlist: List[str],
        discovery_candidates_only: bool, request_started: float,
    ) -> List[Dict[str, Any]]:
        results = data.get("results") if isinstance(data, dict) else data
        if not isinstance(results, list):
            return []
        configured_engines = [
            value.strip() for value in parse_qs(parsed.query).get("engines", [""])[0].split(",")
            if value.strip()
        ]
        engine_failures = _engine_failure_rows(
            data.get("unresponsive_engines") if isinstance(data, dict) else None
        )
        responded_engines: set[str] = set()
        out: List[Dict[str, Any]] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            result_engines = row.get("engines") if isinstance(row.get("engines"), list) else []
            for engine in [row.get("engine"), *result_engines]:
                if str(engine or "").strip():
                    responded_engines.add(str(engine).strip())
            result_url = str(row.get("url") or "")
            result_url_parts = urlparse(result_url)
            domain = (result_url_parts.hostname or "").lower()
            public_candidate = bool(
                result_url_parts.scheme == "https" and result_url_parts.hostname
                and not _is_ip_literal(result_url_parts.hostname)
            )
            if not _domain_allowed(domain, allowlist) and not (
                discovery_candidates_only and public_candidate
            ):
                continue
            out.append({
                "title": str(row.get("title") or row.get("name") or "")[:200],
                "snippet": str(
                    row.get("snippet") or row.get("content") or row.get("description") or ""
                )[:400],
                "url": result_url[:500], "source_domain": domain,
                "claim_candidates": list(row.get("claim_candidates") or [])[:16]
                if isinstance(row.get("claim_candidates"), list) else [],
            })
        degradation_reasons: list[str] = []
        failure_text = " ".join(row["reason"].lower() for row in engine_failures)
        if "captcha" in failure_text:
            degradation_reasons.append("engines_captcha")
        if "too many requests" in failure_text or "rate" in failure_text:
            degradation_reasons.append("engines_rate_limited")
        if engine_failures and not degradation_reasons:
            degradation_reasons.append("engines_unresponsive")
        if not out:
            degradation_reasons.append("zero_allowlisted_results")
        latency_ms = round((time.perf_counter() - request_started) * 1000, 3)
        self.last_receipt.update({
            "raw_result_count": len(results), "result_count": len(results),
            "allowlisted_result_count": len(out), "engines_queried": configured_engines,
            "engines_responded": sorted(responded_engines),
            "engine_failures": engine_failures, "degradation_reasons": degradation_reasons,
            "provider_status": "degraded" if degradation_reasons else "completed",
            "request_latency_ms": latency_ms,
        })
        self._engine_reliability.record(
            endpoint=endpoint, receipt=self.last_receipt, latency_ms=latency_ms,
        )
        reliability = self._engine_reliability.snapshots(endpoint)
        self.last_receipt.update({
            "engine_reliability": reliability,
            "suppressed_engines": [row["engine"] for row in reliability if row["suppressed"]],
        })
        return out


__all__ = ["AsyncHttpxResearchFetcher", "HttpxResearchFetcher"]
