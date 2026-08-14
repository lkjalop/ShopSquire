"""Trust/readiness summary for one Hippograph evidence path.

This does not turn relatedness into correctness.  It tells consumers whether
the path is composed of observations, attestations, inferences, stale facts,
or records whose authority was not supplied.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class HippographPathTrust(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["hippograph-path-trust-v1"] = "hippograph-path-trust-v1"
    evidence_records: int
    signal_classes: dict[str, int]
    authorities: dict[str, int]
    observation_states: dict[str, int]
    unknown_authority_records: int
    stale_or_contradicted_records: int
    inferred_records: int
    status: Literal["healthy", "conditional", "insufficient"]
    limitations: list[str]
    authority: Literal["evidence_quality_only"] = "evidence_quality_only"


def project_path_trust(path: dict[str, Any]) -> HippographPathTrust:
    evidence = [
        record
        for edge in list(path.get("edges") or [])
        for record in list((edge or {}).get("evidence") or [])
        if isinstance(record, dict)
    ]
    signals = Counter(str(row.get("signal_class") or "unclassified") for row in evidence)
    authorities = Counter(str(row.get("source_authority") or "unspecified") for row in evidence)
    states = Counter(
        str(
            row.get("measurement_state")
            or (row.get("attributes") or {}).get("measurement_state")
            or "not_recorded"
        )
        for row in evidence
    )
    unknown = sum(count for key, count in authorities.items() if key in {"", "unspecified", "unknown"})
    stale = sum(count for key, count in states.items() if key in {"stale", "contradicted"})
    inferred = signals.get("inferred", 0)
    limitations: list[str] = []
    if not evidence:
        limitations.append("No evidence records were attached to this relatedness path.")
    if unknown:
        limitations.append("One or more path records do not name a source authority.")
    if inferred:
        limitations.append("Inferred relations require corroboration before product-fit use.")
    if stale:
        limitations.append("Stale or contradicted records remain visible but are conditional.")
    status = (
        "insufficient" if not evidence
        else "conditional" if unknown or inferred or stale
        else "healthy"
    )
    return HippographPathTrust(
        evidence_records=len(evidence), signal_classes=dict(sorted(signals.items())),
        authorities=dict(sorted(authorities.items())), observation_states=dict(sorted(states.items())),
        unknown_authority_records=unknown, stale_or_contradicted_records=stale,
        inferred_records=inferred, status=status, limitations=limitations,
    )


__all__ = ["HippographPathTrust", "project_path_trust"]
