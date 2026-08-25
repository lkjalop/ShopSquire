"""Resolve buyer-supplied official URLs or vendor names without granting authority.

Resolution is deliberately local and zero-network.  It maps a buyer hint onto
the reviewed source registry; a separate, explicitly authorized step may fetch
the enrolled canonical origin and compile claims.
"""
from __future__ import annotations

import re
from typing import Any, Literal, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from src.app.services.official_source_governance import load_official_source_manifest


class BuyerEvidenceSourceCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    publisher: str
    canonical_url: str
    match_basis: Literal["canonical_url", "canonical_descendant", "enrolled_domain", "vendor_name"]
    review_status: str
    research_eligible: bool


class BuyerEvidenceSourceResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "ambiguous", "not_enrolled", "invalid"]
    resolution_owner: Literal["research"] = "research"
    submitted_url: str | None = None
    vendor_name: str | None = None
    candidates: list[BuyerEvidenceSourceCandidate]
    selected_source_id: str | None = None
    external_calls: Literal[0] = 0
    paid_calls: Literal[0] = 0
    reason: str


def _origin_key(value: str) -> tuple[str, str] | None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    host = parsed.hostname.lower().rstrip(".")
    path = "/" + str(parsed.path or "/").strip("/")
    return host, path.rstrip("/") or "/"


def _words(value: str) -> set[str]:
    ignored = {"official", "docs", "documentation", "requirements", "and", "or", "the"}
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if len(token) > 1 and token not in ignored
    }


def _candidate(source: dict[str, Any], basis: str, canonical_url: str) -> BuyerEvidenceSourceCandidate:
    return BuyerEvidenceSourceCandidate(
        source_id=str(source["source_id"]), publisher=str(source["publisher"]),
        canonical_url=canonical_url, match_basis=basis,
        review_status=str(source.get("review_status") or "unknown"),
        research_eligible=source.get("review_status") == "approved",
    )


def resolve_buyer_evidence_source(
    *, source_url: str | None = None, vendor_name: str | None = None,
    sources: Sequence[dict[str, Any]] | None = None,
) -> BuyerEvidenceSourceResolution:
    """Map one buyer hint to reviewed registry entries without fetching it."""

    if bool(str(source_url or "").strip()) == bool(str(vendor_name or "").strip()):
        return BuyerEvidenceSourceResolution(
            status="invalid", submitted_url=source_url, vendor_name=vendor_name,
            candidates=[], reason="provide_exactly_one_url_or_vendor_name",
        )
    registry = list(sources) if sources is not None else list(
        load_official_source_manifest().get("sources") or []
    )
    matches: list[BuyerEvidenceSourceCandidate] = []
    if source_url:
        submitted = _origin_key(source_url)
        if submitted is None:
            return BuyerEvidenceSourceResolution(
                status="invalid", submitted_url=source_url, candidates=[],
                reason="official_evidence_url_must_be_https_without_credentials",
            )
        submitted_host, submitted_path = submitted
        host_sources: dict[str, dict[str, Any]] = {}
        for source in registry:
            if submitted_host in {
                str(domain).strip().lower().rstrip(".")
                for domain in source.get("allowed_domains") or []
            }:
                source_id = str(source.get("source_id") or "")
                host_sources[source_id] = source
        for source in registry:
            for canonical in source.get("canonical_entrypoints") or []:
                canonical_key = _origin_key(str(canonical))
                if canonical_key is None:
                    continue
                canonical_host, canonical_path = canonical_key
                if submitted_host != canonical_host:
                    continue
                if submitted_path == canonical_path:
                    matches.append(_candidate(source, "canonical_url", str(canonical)))
                    break
                if submitted_path.startswith(canonical_path.rstrip("/") + "/"):
                    matches.append(_candidate(source, "canonical_descendant", str(canonical)))
                    break
        # A buyer may paste an obsolete or moved page on a domain owned by exactly one
        # enrolled source. Resolve it to that source's reviewed canonical entrypoint;
        # never fetch or trust the arbitrary pasted path itself.
        if not matches and len(host_sources) == 1:
            source = next(iter(host_sources.values()))
            entrypoints = list(source.get("canonical_entrypoints") or [])
            if entrypoints:
                matches.append(_candidate(source, "enrolled_domain", str(entrypoints[0])))
    else:
        query_words = _words(str(vendor_name))
        if not query_words:
            return BuyerEvidenceSourceResolution(
                status="invalid", vendor_name=vendor_name, candidates=[],
                reason="vendor_name_has_no_resolvable_tokens",
            )
        for source in registry:
            haystack = " ".join([
                str(source.get("source_id") or "").replace("_", " "),
                str(source.get("publisher") or ""),
                " ".join(source.get("allowed_domains") or []),
            ])
            if query_words <= _words(haystack):
                entrypoints = list(source.get("canonical_entrypoints") or [])
                if entrypoints:
                    matches.append(_candidate(source, "vendor_name", str(entrypoints[0])))
    # One source can expose multiple canonical URLs; candidate identity is the
    # source, and the registry-defined first canonical is the safe fetch target.
    unique = {row.source_id: row for row in matches}
    matches = sorted(unique.values(), key=lambda row: row.source_id)
    eligible = [row for row in matches if row.research_eligible]
    status: Literal["resolved", "ambiguous", "not_enrolled", "invalid"]
    if len(matches) == 1 and len(eligible) == 1:
        status, reason = "resolved", "reviewed_source_matched"
    elif len(matches) > 1:
        status, reason = "ambiguous", "multiple_enrolled_sources_match"
    elif matches:
        status, reason = "not_enrolled", "matched_source_requires_independent_review"
    else:
        status, reason = "not_enrolled", "no_canonical_enrolled_source_matched"
    return BuyerEvidenceSourceResolution(
        status=status, submitted_url=source_url, vendor_name=vendor_name,
        candidates=matches,
        selected_source_id=eligible[0].source_id if status == "resolved" else None,
        reason=reason,
    )


__all__ = [
    "BuyerEvidenceSourceCandidate", "BuyerEvidenceSourceResolution",
    "resolve_buyer_evidence_source",
]
