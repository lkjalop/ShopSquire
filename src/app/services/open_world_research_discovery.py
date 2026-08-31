"""Bounded discovery for cases that do not yet have an enrolled publisher."""
from __future__ import annotations

import re
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from src.app.adapters.external_research_httpx import (
    AsyncHttpxResearchFetcher,
    HttpxResearchFetcher,
)
from src.app.services.case_research_plan import CaseResearchPlan
from src.app.services.cancellable_await import await_with_polling_cancel


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
_COMPOUND_PUBLIC_SUFFIXES = {
    "com.au", "net.au", "org.au", "co.nz", "co.uk", "org.uk", "ac.uk",
    "co.jp", "co.kr", "com.br", "com.cn", "com.sg", "com.mx", "co.za",
}


def _registrable_domain(hostname: str) -> str:
    """Conservatively collapse common subdomains without substring matching."""

    host = str(hostname or "").strip(".").lower()
    labels = [label for label in host.split(".") if label]
    if len(labels) <= 2:
        return host
    suffix2 = ".".join(labels[-2:])
    if suffix2 in _COMPOUND_PUBLIC_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


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
    axis_count = len(set(row.get("query_axes") or []))
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
    elif subject_overlap >= 2 and axis_count >= 2 and documentation_surface:
        status = "plausible_documentation_origin"
    elif subject_overlap > 0 and documentation_surface:
        status = "related_documentation_ownership_unverified"
    else:
        status = "publisher_ownership_unresolved"
    confidence = min(
        0.95,
        0.15 + 0.25 * host_overlap + 0.08 * subject_overlap
        + (0.15 if documentation_surface else 0.0) + min(0.15, 0.05 * axis_count),
    )
    return {
        "status": status,
        "confidence": round(confidence, 3),
        "signals": {
            "named_subject_in_host": host_overlap > 0,
            "subject_overlap_count": subject_overlap,
            "independent_query_axis_count": axis_count,
            "documentation_surface": documentation_surface,
            "excluded_intermediary": excluded_intermediary,
        },
        "authority": "candidate_only",
        "ownership_basis": "semantic_origin_signals_only",
        "resolution_owner": "research_or_tenant_policy",
    }


def discover_open_world_publishers(
    plan: CaseResearchPlan,
    *,
    search_url_template: str,
    fetcher: DiscoveryFetcher | None = None,
    timeout_s: float = 12.0,
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
                "registrable_domain": _registrable_domain(host),
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
            host_terms = _terms(candidate["registrable_domain"].replace(".", " "))
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
    engine_failures = list({
        (str(failure.get("engine") or "unknown"), str(failure.get("reason") or "unresponsive")):
        dict(failure)
        for receipt in receipts
        for failure in receipt.get("engine_failures") or []
    }.values())
    evidence_ladder = [
        {
            "tier": 0, "mechanism": "sealed_corpus",
            "execution_status": "not_applicable_novel_publisher",
            "billing_class": "not_applicable",
        },
        {
            "tier": 1, "mechanism": "governed_evidence_cache",
            "execution_status": "not_attempted",
            "rejection_reason": "publisher_not_yet_accepted",
            "billing_class": "not_applicable",
        },
        {
            "tier": 2, "mechanism": "buyer_upload_or_link",
            "execution_status": "available_not_selected",
            "billing_class": "free",
        },
        {
            "tier": 3, "mechanism": "canonical_official_origin",
            "execution_status": "not_attempted",
            "rejection_reason": "publisher_approval_required",
            "billing_class": "free",
        },
        {
            "tier": 4, "mechanism": "self_hosted_discovery",
            "execution_status": (
                "cancelled" if cancelled
                else "degraded" if engine_failures
                else "completed" if external_calls
                else "not_executed"
            ),
            "billing_class": "free",
            "dispatch_count": external_calls,
            "allowlisted_result_count": sum(
                int(row.get("allowlisted_result_count") or 0) for row in receipts
            ),
            "engines_queried": sorted({
                str(engine) for row in receipts for engine in row.get("engines_queried") or []
            }),
            "engines_responded": sorted({
                str(engine) for row in receipts for engine in row.get("engines_responded") or []
            }),
            "engine_failures": engine_failures,
            "engine_reliability": [
                dict(engine)
                for row in receipts
                for engine in row.get("engine_reliability") or []
            ],
            "suppressed_engines": sorted({
                str(engine) for row in receipts for engine in row.get("suppressed_engines") or []
            }),
        },
        {
            "tier": 5, "mechanism": "paid_discovery",
            "execution_status": "not_attempted",
            "rejection_reason": "provider_not_enrolled",
            "billing_class": "paid", "paid_calls": 0,
        },
        {
            "tier": 6, "mechanism": "publisher_policy_resolution",
            "execution_status": "required",
            "rejection_reason": "discovery_does_not_establish_authority",
            "billing_class": "not_applicable",
        },
    ]
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
        "evidence_ladder": evidence_ladder,
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


async def discover_open_world_publishers_async(
    plan: CaseResearchPlan,
    *,
    search_url_template: str,
    timeout_s: float = 12.0,
    cancellation_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Cancellable live transport with the exact synchronous projection semantics."""

    transport = AsyncHttpxResearchFetcher(
        search_url_template=search_url_template, allow_private=True,
    )
    per_query = max(1.0, min(4.0, timeout_s / max(1, len(plan.discovery_queries))))
    replay_rows: list[tuple[list[dict[str, Any]], dict[str, Any]]] = []
    for item in plan.discovery_queries[:3]:
        if cancellation_requested and cancellation_requested():
            break
        rows, cancelled = await await_with_polling_cancel(
            transport.fetch_async(
                item.query, allowlist=[], timeout_s=per_query,
                discovery_candidates_only=True,
            ),
            cancellation_requested=cancellation_requested,
        )
        if cancelled:
            break
        rows = rows or []
        replay_rows.append((rows, dict(transport.last_receipt or {})))
        if cancellation_requested and cancellation_requested():
            break

    class ReplayFetcher:
        def __init__(self) -> None:
            self.index = 0
            self.last_receipt: dict[str, Any] = {}

        def fetch(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
            if self.index >= len(replay_rows):
                self.last_receipt = {
                    "execution_status": "not_dispatched",
                    "external_call_dispatched": False,
                }
                return []
            rows, receipt = replay_rows[self.index]
            self.index += 1
            self.last_receipt = dict(receipt)
            return list(rows)

    replay = ReplayFetcher()
    return discover_open_world_publishers(
        plan, search_url_template=search_url_template, fetcher=replay,
        timeout_s=timeout_s, cancellation_requested=cancellation_requested,
    )


__all__ = ["discover_open_world_publishers", "discover_open_world_publishers_async"]
