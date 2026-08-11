"""Bounded discovery for cases that do not yet have an enrolled publisher."""
from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlparse

from src.app.adapters.external_research_httpx import HttpxResearchFetcher
from src.app.services.case_research_plan import CaseResearchPlan


class DiscoveryFetcher(Protocol):
    last_receipt: dict[str, Any]

    def fetch(
        self, query: str, *, allowlist: list[str], timeout_s: float,
        discovery_candidates_only: bool,
    ) -> list[dict[str, Any]]: ...


def _quality_score(row: dict[str, Any]) -> int:
    url = str(row.get("url") or "")
    title = str(row.get("title") or "").lower()
    path = str(urlparse(url).path or "").lower()
    host = str(urlparse(url).hostname or "").lower()
    score = 0
    if any(token in path for token in ("requirements", "system-requirements", "manual", "support")):
        score += 4
    if any(token in title for token in ("requirements", "documentation", "manual", "support")):
        score += 3
    if host.startswith(("docs.", "documentation.", "help.", "support.")):
        score += 4
    if "official" in title:
        score += 2
    if any(token in path for token in ("forum", "community", "blog", "reddit")):
        score -= 4
    if any(token in host for token in (
        "facebook.", "reddit.", "wikipedia.", "alibaba.", "dictionary.", "youtube.",
    )):
        score -= 8
    return score


def _quality(row: dict[str, Any]) -> tuple[int, str]:
    return (-_quality_score(row), str(row.get("url") or ""))


def discover_open_world_publishers(
    plan: CaseResearchPlan,
    *,
    search_url_template: str,
    fetcher: DiscoveryFetcher | None = None,
    timeout_s: float = 9.0,
) -> dict[str, Any]:
    """Discover candidate origins; never fetch them or compile their snippets as claims."""

    if plan.publisher_status != "unresolved":
        raise ValueError("open_world_plan_required")
    transport = fetcher or HttpxResearchFetcher(
        search_url_template=search_url_template, allow_private=True,
    )
    candidates: dict[str, dict[str, Any]] = {}
    receipts: list[dict[str, Any]] = []
    per_query = max(1.0, min(4.0, timeout_s / max(1, len(plan.discovery_queries))))
    for item in plan.discovery_queries[:3]:
        rows = transport.fetch(
            item.query, allowlist=[], timeout_s=per_query,
            discovery_candidates_only=True,
        )
        receipt = dict(transport.last_receipt or {})
        receipt.update({
            "query_id": item.query_id,
            "query_axis": item.axis,
            "query_text_retained": False,
            "billing_class": "free",
            "result_count": len(rows),
        })
        receipts.append(receipt)
        for row in rows:
            url = str(row.get("url") or "")
            host = str(urlparse(url).hostname or "").lower()
            if not url.startswith("https://") or not host:
                continue
            candidates.setdefault(url, {
                "url": url,
                "domain": host,
                "title": str(row.get("title") or "")[:200],
                "discovery_only": True,
                "authority": "not_accepted",
            })
    # Do not present arbitrary search results as possible authorities.  A row
    # must at least look like requirements, documentation, a manual, or a
    # publisher support surface. Publisher ownership is still unresolved and
    # must be approved separately.
    ranked = sorted(
        (row for row in candidates.values() if _quality_score(row) >= 3),
        key=_quality,
    )[:12]
    external_calls = sum(bool(row.get("external_call_dispatched")) for row in receipts)
    return {
        "schema_version": "open-world-discovery-v1",
        "status": "publisher_candidates_found" if ranked else "no_publisher_candidates",
        "publisher_status": "unresolved",
        "candidates": ranked,
        "receipts": receipts,
        "provider_accounting": {
            "discovery_calls": external_calls,
            "external_calls": external_calls,
            "official_origin_fetches": 0,
            "paid_calls": 0,
        },
        "claims": [],
        "next_action": "approve_publisher_origin_or_upload_requirements",
    }


__all__ = ["discover_open_world_publishers"]
