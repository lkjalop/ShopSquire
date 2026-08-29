"""Resolve buyer-supplied official URLs or vendor names without granting authority.

Resolution is deliberately local and zero-network.  It maps a buyer hint onto
the reviewed source registry; a separate, explicitly authorized step may fetch
the enrolled canonical origin and compile claims.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Literal, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from src.app.services.official_source_governance import load_official_source_manifest


_SUBMITTED_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def extract_submitted_source_url(value: str | None) -> str | None:
    """Extract one bounded buyer URL before semantic routing or persistence."""
    match = _SUBMITTED_URL_RE.search(str(value or ""))
    if not match:
        return None
    return match.group(0).rstrip("),.;]")[:2000]


def remove_submitted_source_urls(value: str | None) -> str:
    """Remove raw URLs from model/catalog input while preserving the buyer's purpose."""
    sanitized = _SUBMITTED_URL_RE.sub(" [submitted official source] ", str(value or ""))
    return re.sub(r"\s+", " ", sanitized).strip()


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
    # Sanitized display URL only: credentials, query, and fragment are never
    # returned or persisted in Decision Trace.
    submitted_url: str | None = None
    submitted_url_hash: str | None = None
    submitted_host: str | None = None
    submitted_path_hash: str | None = None
    vendor_name: str | None = None
    candidates: list[BuyerEvidenceSourceCandidate]
    selected_source_id: str | None = None
    external_calls: Literal[0] = 0
    paid_calls: Literal[0] = 0
    reason: str
    security_status: Literal[
        "canonical_fetch_eligible", "blocked", "unresolved",
    ] = "unresolved"
    canonical_fetch_eligible: bool = False
    link_assessment: dict[str, Any] | None = None


def _origin_key(value: str) -> tuple[str, str] | None:
    parsed = urlparse(str(value or "").strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    host = parsed.hostname.lower().rstrip(".")
    path = "/" + str(parsed.path or "/").strip("/")
    return host, path.rstrip("/") or "/"


def _submitted_url_metadata(value: str | None) -> dict[str, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return {
            "submitted_url": None, "submitted_url_hash": None,
            "submitted_host": None, "submitted_path_hash": None,
        }
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    parsed = urlparse(raw)
    host = str(parsed.hostname or "").lower().rstrip(".") or None
    path = "/" + str(parsed.path or "/").strip("/")
    path = path.rstrip("/") or "/"
    safe_url = None
    if parsed.scheme.lower() == "https" and host and not parsed.username and not parsed.password:
        safe_url = f"https://{host}{path}"
    return {
        "submitted_url": safe_url,
        "submitted_url_hash": digest,
        "submitted_host": host,
        "submitted_path_hash": hashlib.sha256(path.encode("utf-8")).hexdigest(),
    }


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
    retained_purpose: str | None = None,
) -> BuyerEvidenceSourceResolution:
    """Map one buyer hint to reviewed registry entries without fetching it."""

    submitted_metadata = _submitted_url_metadata(source_url)
    from src.app.services.buyer_link_assessment import assess_buyer_link

    link_assessment = (
        assess_buyer_link(source_url=source_url, retained_purpose=retained_purpose)
        if source_url else None
    )
    if bool(str(source_url or "").strip()) == bool(str(vendor_name or "").strip()):
        return BuyerEvidenceSourceResolution(
            status="invalid", **submitted_metadata, vendor_name=vendor_name,
            candidates=[], reason="provide_exactly_one_url_or_vendor_name",
            security_status="blocked", link_assessment=link_assessment,
        )
    registry = list(sources) if sources is not None else list(
        load_official_source_manifest().get("sources") or []
    )
    matches: list[BuyerEvidenceSourceCandidate] = []
    if source_url:
        submitted = _origin_key(source_url)
        if submitted is None:
            return BuyerEvidenceSourceResolution(
                status="invalid", **submitted_metadata, candidates=[],
                reason="official_evidence_url_must_be_https_without_credentials",
                security_status="blocked", link_assessment=link_assessment,
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
        status=status, **submitted_metadata, vendor_name=vendor_name,
        candidates=matches,
        selected_source_id=eligible[0].source_id if status == "resolved" else None,
        reason=reason,
        security_status=(
            "canonical_fetch_eligible" if status == "resolved" else
            "blocked" if status == "invalid" else "unresolved"
        ),
        canonical_fetch_eligible=status == "resolved",
        link_assessment=link_assessment,
    )


__all__ = [
    "BuyerEvidenceSourceCandidate", "BuyerEvidenceSourceResolution",
    "extract_submitted_source_url", "remove_submitted_source_urls",
    "resolve_buyer_evidence_source",
]
