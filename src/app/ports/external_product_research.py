"""ExternalProductResearchPort — injectable boundary for SAFE web product research.

The fetcher is INJECTED so the guardrailed service (external_product_research_service) is fully
testable without network. The real adapter (httpx to an allowlist) is supplied only in a networked
deployment; in dev/test a fake/null fetcher is used.

Contract: the fetcher receives an ALREADY PII-SCRUBBED query, must hit ONLY allowlisted domains,
must NOT raise (fail open to []), and returns raw hits as plain dicts:
    {"title", "snippet", "url", "source_domain", "name"?, "model"?, "sku"?, "price"?}
The fetched text is DATA for display only — it is never executed as instructions.
"""
from __future__ import annotations

from typing import Any, Dict, List, Protocol, runtime_checkable


@runtime_checkable
class ExternalResearchFetcher(Protocol):
    def fetch(self, scrubbed_query: str, *, allowlist: List[str], timeout_s: float = 4.0) -> List[Dict[str, Any]]:
        ...


class NullFetcher:
    """Default fetcher: no network. Returns no hits. Safe to wire on the live path before a real
    allowlisted httpx adapter exists — external research stays 'empty', never errors."""

    def fetch(self, scrubbed_query: str, *, allowlist: List[str], timeout_s: float = 4.0) -> List[Dict[str, Any]]:
        return []
