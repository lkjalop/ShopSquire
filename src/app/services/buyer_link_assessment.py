"""Deterministic, zero-fetch assessment for buyer-submitted web links.

The assessment is deliberately about *routing and authority*, not truth.  URL
tokens and reviewed publisher classes can establish that a page is likely
relevant context, secondary corroboration, or unrelated to the retained buyer
purpose.  They can never establish a hardware requirement or product fit.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import parse_qsl, urlparse


_TRACKING_KEYS = {
    "gclid", "gbraid", "wbraid", "gad_source", "gad_campaignid",
    "fbclid", "msclkid", "mc_cid", "mc_eid",
}

_KNOWN_SOURCE_CLASSES = {
    "cupix.com": "official_publisher",
    "www.cupix.com": "official_publisher",
    "anylogic.com": "official_publisher",
    "www.anylogic.com": "official_publisher",
    "thectoclub.com": "secondary_commentary",
    "www.thectoclub.com": "secondary_commentary",
    "fextralife.com": "community_wiki",
    "darkheresy.wiki.fextralife.com": "community_wiki",
    "systemrequirementslab.com": "secondary_requirements_aggregator",
    "www.systemrequirementslab.com": "secondary_requirements_aggregator",
}

_DIGITAL_TWIN_TERMS = {
    "digital", "twin", "simulation", "factory", "plc", "manufacturing",
    "cupix", "cupixworks", "anylogic", "emulate3d", "sim3d",
}
_GAME_TERMS = {
    "game", "gaming", "play", "baldur", "heroes", "might", "magic",
    "baldursgate3", "flight", "simulator", "dark", "heresy",
}
_REQUIREMENT_TERMS = {
    "requirements", "requirement", "specifications", "specification",
    "hardware", "compatibility", "supported", "minimum", "recommended",
}


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def _private_or_special_host(host: str) -> bool:
    if host in {"localhost", "metadata", "metadata.google.internal", "169.254.169.254"}:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified
    )


def _source_class(host: str) -> str:
    direct = _KNOWN_SOURCE_CLASSES.get(host)
    if direct:
        return direct
    for domain, source_class in _KNOWN_SOURCE_CLASSES.items():
        if host.endswith("." + domain):
            return source_class
    return "unverified_web_source"


def assess_buyer_link(*, source_url: str | None, retained_purpose: str | None) -> dict[str, Any]:
    """Return a bounded source/relevance/security receipt without fetching."""

    raw = str(source_url or "").strip()
    parsed = urlparse(raw)
    host = str(parsed.hostname or "").lower().rstrip(".")
    syntax_safe = bool(
        parsed.scheme.lower() == "https" and host
        and not parsed.username and not parsed.password
        and not _private_or_special_host(host)
    )
    query_keys = [key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    tracking_removed = sum(
        1 for key in query_keys if key.startswith("utm_") or key in _TRACKING_KEYS
    )
    source_class = _source_class(host) if host else "invalid"

    purpose_tokens = _tokens(str(retained_purpose or ""))
    link_tokens = _tokens(" ".join((host, parsed.path)))
    purpose_domain = (
        "digital_twin" if purpose_tokens & _DIGITAL_TWIN_TERMS else
        "gaming" if purpose_tokens & _GAME_TERMS else "unresolved"
    )
    link_domain = (
        "digital_twin" if link_tokens & _DIGITAL_TWIN_TERMS else
        "gaming" if link_tokens & _GAME_TERMS else "unresolved"
    )
    if not syntax_safe:
        relevance = "not_assessed"
        recommended_use = "block_before_fetch"
    elif purpose_domain != "unresolved" and link_domain != "unresolved" and purpose_domain != link_domain:
        relevance = "irrelevant_to_retained_purpose"
        recommended_use = "reject_for_this_case_and_request_a_relevant_source"
    elif source_class == "official_publisher":
        if link_tokens & _REQUIREMENT_TERMS:
            relevance = "likely_relevant_requirements_candidate"
            recommended_use = "resolve_to_reviewed_canonical_origin_before_claim_compilation"
        else:
            relevance = "likely_relevant_context_only"
            recommended_use = "use_for_identity_or_context_then_find_official_requirements"
    elif source_class in {"secondary_commentary", "secondary_requirements_aggregator"}:
        relevance = (
            "likely_relevant_secondary" if purpose_domain == link_domain and link_domain != "unresolved"
            else "relevance_unresolved"
        )
        recommended_use = "discovery_or_corroboration_only_not_requirement_authority"
    elif source_class == "community_wiki":
        relevance = (
            "likely_relevant_context_only" if purpose_domain == link_domain and link_domain != "unresolved"
            else "relevance_unresolved"
        )
        recommended_use = "context_only_then_find_official_publisher_requirements"
    else:
        relevance = "relevance_unresolved"
        recommended_use = "do_not_fetch_until_origin_and_purpose_are_resolved"

    security_status = "eligible_for_guarded_resolution" if syntax_safe else "blocked"
    control_hypotheses = [] if syntax_safe else [
        {
            "framework": "OWASP API Security Top 10 2023",
            "control": "API7:2023 Server Side Request Forgery",
            "status": "design_control_triggered_not_incident_attribution",
        }
    ]
    return {
        "schema_version": "buyer-link-assessment-v1",
        "source_class": source_class,
        "relevance": relevance,
        "recommended_use": recommended_use,
        "purpose_domain": purpose_domain,
        "link_domain": link_domain,
        "security_status": security_status,
        "tracking_parameters_removed": tracking_removed,
        "query_parameters_persisted": False,
        "credentials_persisted": False,
        "content_executed_as_instructions": False,
        "requirement_authority": "none",
        "product_fit_authority": "none",
        "commerce_authority": "none",
        "control_hypotheses": control_hypotheses,
        "threat_intel": {
            "status": "not_observed_zero_fetch_intake",
            "incident_tags": [],
            "note": "Framework incident tags require observed reputation or content evidence.",
        },
    }


__all__ = ["assess_buyer_link"]
