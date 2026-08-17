"""Buyer-safe views over immutable procurement decision runs.

These projections never re-evaluate a case and never imply that historical
supplier or inventory evidence is still current.  They make the time boundary
explicit so Decision Trace can answer three different questions without
silently mixing them.
"""
from __future__ import annotations

from typing import Any, Iterable


def _supplier_candidates(fulfilment: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for offer in fulfilment.get("offers") or []:
        provenance = offer.get("provenance") or {}
        candidates.append({
            "supplier_reference": provenance.get("supplier_reference") or "not_disclosed",
            "offered_sku": offer.get("offered_sku"),
            "relationship": offer.get("relationship"),
            "quantity_available": offer.get("quantity_available"),
            "lead_time_days": offer.get("lead_time_days"),
            "response_status": offer.get("response_status") or "unverified",
            "trust_status": offer.get("trust_status") or "unverified",
            "validity_expires_at": offer.get("validity_expires_at"),
        })
    return candidates


def project_decision_trace_views(*, latest: Any, history: Iterable[Any]) -> dict[str, Any]:
    """Project revision delta, historical knowledge, and fulfilment evidence."""

    runs = list(history)
    previous = runs[-2] if len(runs) > 1 else None
    state = latest.snapshot.case_state.model_dump(mode="json")
    fulfilment = dict(state.get("fulfilment") or {})
    invalidations = [row.model_dump(mode="json") for row in latest.invalidations]
    return {
        "what_changed": {
            "from_revision": previous.snapshot.case_revision if previous else None,
            "to_revision": latest.snapshot.case_revision,
            "invalidation_count": len(invalidations),
            "invalidations": invalidations,
            "recomputed_stages": sorted({
                stage
                for row in invalidations
                for stage in row.get("invalidated_stages") or []
            }),
            "status": "recorded_changes" if invalidations else "no_invalidation_recorded",
        },
        "what_was_known_then": {
            "knowledge_cutoff": latest.snapshot.knowledge_cutoff,
            "evaluation_time": latest.snapshot.evaluation_time,
            "evidence_watermarks": [
                row.model_dump(mode="json") for row in latest.snapshot.evidence_watermarks
            ],
            "future_evidence_excluded": True,
        },
        "who_can_fulfil_now": {
            "as_of": latest.snapshot.evaluation_time,
            "evidence_warning": (
                "This is the latest recorded case evidence, not a live stock promise."
            ),
            "selected_sku": state.get("selected_sku"),
            "requested_quantity": state.get("requested_quantity"),
            "available_now": fulfilment.get("available_now"),
            "selection": fulfilment.get("choice"),
            "supplier_candidates": _supplier_candidates(fulfilment),
            "resolution_owner": (state.get("authority") or {}).get("resolution_owner"),
        },
    }


__all__ = ["project_decision_trace_views"]
