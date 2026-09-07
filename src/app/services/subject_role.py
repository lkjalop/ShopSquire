"""Closed subject-role proposal with deterministic commerce validation.

Taxonomy identifies *what* an entity is.  This contract identifies the role that
entity plays in the current turn.  In particular, a software node is not inherently
a workload: buyers can procure software or procure hardware that runs it.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping, Optional

from src.app.services.recommendation_core.turn_outcome import EntityFrame


class SubjectRole(str, Enum):
    PROCURE_SUBJECT = "PROCURE_SUBJECT"
    RUN_SUBJECT_ON_PRODUCT = "RUN_SUBJECT_ON_PRODUCT"
    COMPATIBILITY_CHECK = "COMPATIBILITY_CHECK"
    ADJACENT_PRODUCT = "ADJACENT_PRODUCT"
    UNRESOLVED = "UNRESOLVED"


_COMMERCIAL = re.compile(
    r"\b(?:buy|purchase|procure|source|quote|rfq|licen[cs]e(?:s|d)?|subscription|subscribe|"
    r"renew(?:al)?|seats?|endpoints?|per\s+(?:user|seat|device|endpoint))\b", re.I,
)
_DEVICE = re.compile(
    r"\b(?:laptop|notebook|workstation|desktop|computer|pc|server|tablet|phone|hardware|machine|device)s?\b", re.I,
)
_HARDWARE_PRODUCT = re.compile(
    r"\b(?:laptop|notebook|workstation|desktop|computer|pc|server|tablet|phone|hardware|machine)s?\b", re.I,
)
_RUN = re.compile(
    r"\b(?:play|playing|run|running|render|rendering|edit|editing|stream|streaming|"
    r"develop|development|process|processing|simulate|simulation)\b", re.I,
)
_COMPAT = re.compile(
    r"\b(?:compatible|compatibility|compare|versus|vs\.?|requirements?|"
    r"specs?|recommended\s+(?:specs?|requirements?))\b",
    re.I,
)
_SOFTWARE_COMMERCE = re.compile(
    r"\b(?:software|saas|platform|suite|licen[cs]e(?:s)?|subscription|"
    r"seats?|per\s+(?:user|seat|endpoint))\b", re.I,
)


def propose_subject_role(query: str) -> SubjectRole:
    q = str(query or "")
    commercial = bool(_COMMERCIAL.search(q))
    device = bool(_DEVICE.search(q))
    run = bool(_RUN.search(q))
    if _COMPAT.search(q):
        return SubjectRole.COMPATIBILITY_CHECK
    if commercial:
        return SubjectRole.PROCURE_SUBJECT
    if device and not run and re.search(
        r"\b(?:need|want|order|obtain|get|looking\s+for)\b", q, re.I,
    ):
        return SubjectRole.PROCURE_SUBJECT
    if device and run:
        return SubjectRole.RUN_SUBJECT_ON_PRODUCT
    if run:
        return SubjectRole.RUN_SUBJECT_ON_PRODUCT
    return SubjectRole.UNRESOLVED


def is_explicit_software_procurement(query: str) -> bool:
    """True for literal software commercial forms, not application-name lists."""
    q = str(query or "")
    return bool(_SOFTWARE_COMMERCE.search(q) and not _HARDWARE_PRODUCT.search(q))


def has_explicit_workload_relation(query: str) -> bool:
    """Whether the buyer literally stated a capability/workload verb.

    This is a bounded trigger for semantic coverage repair, not an entity
    extractor. In particular, the word ``for`` alone is intentionally not
    authority to claim that a named application exists.
    """
    return bool((_RUN.search(str(query or "")) or _COMPAT.search(str(query or ""))))


def validate_entity_frame(
    query: str,
    proposal: Mapping[str, Any] | None,
    *,
    fallback_role: str = SubjectRole.UNRESOLVED.value,
) -> EntityFrame:
    """Validate an open-vocabulary entity proposal against buyer-authored text.

    Identity text is accepted only when it is literally anchored in the turn.
    The frame remains semantic and cannot grant sellability or research authority.
    """
    raw = proposal if isinstance(proposal, Mapping) else {}
    q = str(query or "")
    identity = str(raw.get("identity") or "").strip()[:160] or None
    buyer_span = str(raw.get("buyer_span") or identity or "").strip()[:240] or None
    q_fold = re.sub(r"\s+", " ", q).casefold()
    if identity and re.sub(r"\s+", " ", identity).casefold() not in q_fold:
        identity = None
    if buyer_span and re.sub(r"\s+", " ", buyer_span).casefold() not in q_fold:
        buyer_span = identity
    category = str(raw.get("entity_category") or "unknown").strip().lower()
    if category not in {"product", "software", "service", "content", "unknown"}:
        category = "unknown"
    proposed_role = str(raw.get("turn_role") or raw.get("subject_role") or fallback_role).upper()
    try:
        role = SubjectRole(proposed_role)
    except ValueError:
        role = SubjectRole.UNRESOLVED
    try:
        confidence = max(0.0, min(float(raw.get("confidence") or 0.0), 1.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return EntityFrame(
        identity=identity,
        entity_category=category,
        turn_role=role.value,
        buyer_span=buyer_span,
        confidence=confidence,
    )


def validate_subject_role(
    query: str,
    *,
    node_handle: Optional[str],
    sold_state: Optional[bool],
    model_proposal: Optional[str] = None,
) -> SubjectRole:
    """Validate a bounded proposal; the model cannot override literal commercial cues.

    ``sold_state`` controls authorization elsewhere.  It is accepted here so callers cannot
    accidentally treat this semantic classification as sellability authority.
    """
    deterministic = propose_subject_role(query)
    try:
        proposed = SubjectRole(str(model_proposal or "").upper())
    except ValueError:
        proposed = SubjectRole.UNRESOLVED
    # Buying the host does not mean buying its workload. Preserve the typed
    # relationship when both the device and execution relation are buyer-authored.
    # This grants no catalog or commerce authority.
    if (
        proposed is SubjectRole.RUN_SUBJECT_ON_PRODUCT
        and _DEVICE.search(str(query or ""))
        and _RUN.search(str(query or ""))
    ):
        return proposed
    if _COMMERCIAL.search(str(query or "")):
        return SubjectRole.PROCURE_SUBJECT
    if proposed in {
        SubjectRole.PROCURE_SUBJECT,
        SubjectRole.RUN_SUBJECT_ON_PRODUCT,
        SubjectRole.COMPATIBILITY_CHECK,
        SubjectRole.ADJACENT_PRODUCT,
    }:
        return proposed
    return deterministic
