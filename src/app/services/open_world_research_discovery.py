"""Bounded discovery for cases that do not yet have an enrolled publisher."""
from __future__ import annotations

import re
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from src.app.adapters.external_research_httpx import HttpxResearchFetcher
from src.app.services.case_research_plan import CaseResearchPlan


class DiscoveryFetcher(Protocol):
    last_receipt: dict[str, Any]

    def fetch(
        self, query: str, *, allowlist: list[str], timeout_s: float,
        discovery_candidates_only: bool,
    ) -> list[dict[str, Any]]: ...


_WORD = re.compile(r"[a-z0-9]+")
_NAMED_SUBJECT = re.compile(r"\b[A-Z][A-Za-z0-9+.-]*(?:\s+[A-Z][A-Za-z0-9+.-]*)*\b")
_QUALITY_STOP = {
    "a", "and", "are", "for", "from", "hardware", "in", "is", "of", "official",
    "only", "or", "requirements", "software", "support", "system", "the", "to",
    "vendor", "with",
}


def _terms(value: str) -> set[str]:
    return {
        token for token in _WORD.findall(str(value or "").lower())
        if len(token) > 2 and token not in _QUALITY_STOP
    }


def _named_subject_terms(value: str) -> set[str]:
    return {
        token
        for phrase in _NAMED_SUBJECT.findall(str(value or ""))
        for token in _terms(phrase)
        if token not in {"can", "could", "exclude", "only", "this", "we", "which", "will"}
    }


def _quality_score(row: dict[str, Any]) -> int:
    url = str(row.get("url") or "")
    title = str(row.get("title") or "").lower()
    path = str(urlparse(url).path or "").lower()
    host = str(urlparse(url).hostname or "").lower()
    score = 0
    if any(token in path for token in ("requirements", "system-requirements")):
        score += 8
    elif any(token in path for token in ("manual", "support")):
        score += 3
    if "requirements" in title:
        score += 7
    elif any(token in title for token in ("documentation", "manual", "support")):
        score += 3
    if host.startswith(("docs.", "documentation.", "help.", "support.")):
        score += 4
    if "official" in title:
        score += 2
    # Independent query axes are weak corroboration that a result is about the
    # retained purpose, not merely a page containing the word "requirements".
    score += min(6, 2 * len(set(row.get("query_axes") or [])))
    score += min(6, 2 * int(row.get("subject_overlap_count") or 0))
    # Prefer a publisher-looking origin whose hostname contains the buyer's
    # named subject over a reseller/blog that repeats that name only in a title
    # or URL path. This remains a discovery hint, never an authority grant.
    score += min(12, 6 * int(row.get("publisher_host_overlap_count") or 0))
    if any(token in path for token in ("forum", "community", "blog", "reddit")):
        score -= 4
    if any(token in host for token in (
        "facebook.", "linkedin.", "reddit.", "wikipedia.", "alibaba.", "dictionary.",
        "youtube.",
    )):
        score -= 20
    return score


def _quality(row: dict[str, Any]) -> tuple[int, str]:
    return (-_quality_score(row), str(row.get("url") or ""))


def _publisher_ownership_evaluation(row: dict[str, Any]) -> dict[str, Any]:
    """Assess whether a result plausibly belongs to the named publisher.

    This is deliberately workload-neutral and does not maintain vendor aliases.
    It evaluates origin shape and semantic overlap only; the result remains a
    candidate and cannot approve a publisher or authorize a claim.
    """
    parsed = urlparse(str(row.get("url") or ""))
    host = str(parsed.hostname or "").lower()
    path = str(parsed.path or "").lower()
    host_overlap = int(row.get("publisher_host_overlap_count") or 0)
    subject_overlap = int(row.get("subject_overlap_count") or 0)
    documentation_surface = bool(
        host.startswith(("docs.", "documentation.", "help.", "support."))
        or any(token in path for token in ("requirements", "system-requirements", "manual", "support"))
    )
    excluded_intermediary = any(token in host for token in (
        "reddit.", "wikipedia.", "youtube.", "linkedin.", "facebook.", "medium.",
    ))
    if excluded_intermediary:
        status = "unlikely_publisher_origin"
    elif host_overlap > 0 and documentation_surface:
        status = "plausible_direct_origin"
    elif subject_overlap > 0 and documentation_surface:
        status = "plausible_documentation_origin"
    else:
        status = "publisher_ownership_unresolved"
    confidence = min(0.95, 0.2 + 0.25 * host_overlap + 0.1 * subject_overlap + (0.2 if documentation_surface else 0.0))
    return {
        "status": status,
        "confidence": round(confidence, 3),
        "signals": {
            "named_subject_in_host": host_overlap > 0,
            "subject_overlap_count": subject_overlap,
            "documentation_surface": documentation_surface,
            "excluded_intermediary": excluded_intermediary,
        },
        "authority": "candidate_only",
        "resolution_owner": "research_or_tenant_policy",
    }


def discover_open_world_publishers(
    plan: CaseResearchPlan,
    *,
    search_url_template: str,
    fetcher: DiscoveryFetcher | None = None,
    timeout_s: float = 9.0,
    cancellation_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Discover candidate origins; never fetch them or compile their snippets as claims."""

    if plan.publisher_status != "unresolved":
        raise ValueError("open_world_plan_required")
    transport = fetcher or HttpxResearchFetcher(
        search_url_template=search_url_template, allow_private=True,
    )
    candidates: dict[str, dict[str, Any]] = {}
    receipts: list[dict[str, Any]] = []
    named_subject_terms = _named_subject_terms(plan.retained_purpose)
    per_query = max(1.0, min(4.0, timeout_s / max(1, len(plan.discovery_queries))))
    cancelled = False
    for item in plan.discovery_queries[:3]:
        if cancellation_requested and cancellation_requested():
            cancelled = True
            break
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
        if cancellation_requested and cancellation_requested():
            cancelled = True
            break
        for row in rows:
            url = str(row.get("url") or "")
            host = str(urlparse(url).hostname or "").lower()
            if not url.startswith("https://") or not host:
                continue
            candidate = candidates.setdefault(url, {
                "url": url,
                "domain": host,
                "title": str(row.get("title") or "")[:200],
                "discovery_only": True,
                "authority": "not_accepted",
                "query_axes": [],
                "query_ids": [],
                "subject_overlap_count": 0,
                "publisher_host_overlap_count": 0,
            })
            candidate["query_axes"] = sorted({*candidate["query_axes"], item.axis})
            candidate["query_ids"] = sorted({*candidate["query_ids"], item.query_id})
            result_terms = _terms(f"{candidate['domain']} {candidate['title']} {urlparse(url).path}")
            purpose_terms = _terms(plan.retained_purpose)
            host_terms = _terms(candidate["domain"].replace(".", " "))
            candidate["subject_overlap_count"] = max(
                int(candidate["subject_overlap_count"]), len(result_terms & purpose_terms),
            )
            candidate["publisher_host_overlap_count"] = max(
                int(candidate["publisher_host_overlap_count"]),
                len(host_terms & named_subject_terms),
            )
    # Do not present arbitrary search results as possible authorities.  A row
    # must at least look like requirements, documentation, a manual, or a
    # publisher support surface. Publisher ownership is still unresolved and
    # must be approved separately.
    ranked = [] if cancelled else sorted(
        (
            row for row in candidates.values()
            if int(row.get("subject_overlap_count") or 0) > 0
            and _quality_score(row) >= 3
        ),
        key=_quality,
    )[:12]
    for row in ranked:
        row["quality_score"] = _quality_score(row)
        row["publisher_ownership_evaluation"] = _publisher_ownership_evaluation(row)
    external_calls = sum(bool(row.get("external_call_dispatched")) for row in receipts)
    return {
        "schema_version": "open-world-discovery-v1",
        "status": (
            "cancelled" if cancelled
            else "publisher_candidates_found" if ranked
            else "no_publisher_candidates"
        ),
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
        "next_action": (
            "explicit_refresh_or_upload_requirements" if cancelled
            else "approve_publisher_origin_or_upload_requirements"
        ),
        "cancellation": {
            "requested": cancelled,
            "remaining_queries_not_dispatched": max(
                0, min(3, len(plan.discovery_queries)) - len(receipts)
            ),
        },
    }


__all__ = ["discover_open_world_publishers"]
