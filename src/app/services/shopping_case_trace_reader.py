"""Bounded retrieval of the trace events that establish a shopping case."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.app.services.decision_log import get_cached_trace_events


def _payload_matches_case(row: dict[str, Any], case_id: str) -> bool:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return False
    return isinstance(payload, dict) and str(payload.get("case_id") or "") == case_id


def _cached_row_matches_tenant(row: dict[str, Any], tenant_id: str) -> bool:
    """Cached trace rows carry the same tenant boundary as durable rows."""
    return str(row.get("tenant_id") or "") == str(tenant_id or "")


def load_case_trace_events(
    db, *, case_id: str, tenant_id: str, decision_trace_id: str | None = None,
) -> list[dict[str, Any]]:
    """Load case events without conflating case and decision-trace identity.

    Continuing cases can receive a new decision trace on every turn.  When the
    caller carries that explicit reference, validate the structured case_id in
    every event before accepting it.  The case-derived trace key remains only a
    compatibility lookup for historical records.
    """

    if decision_trace_id:
        explicit_cached = [
            row for row in get_cached_trace_events(decision_trace_id)
            if _cached_row_matches_tenant(row, tenant_id)
            and _payload_matches_case(row, case_id)
        ]
        if explicit_cached:
            return explicit_cached
        try:
            explicit = db.execute(text(
                "SELECT trace_id, event_type, payload FROM decision_trace_events "
                "WHERE trace_id=:trace_id AND tenant_id=:tenant_id ORDER BY created_at ASC"
            ), {
                "trace_id": decision_trace_id, "tenant_id": tenant_id,
            }).mappings().all()
        except Exception:
            explicit = []
        matched_explicit = [
            dict(row) for row in explicit if _payload_matches_case(dict(row), case_id)
        ]
        if matched_explicit:
            return matched_explicit
        # An explicit reference is authoritative for this operation. Falling
        # through to a historical case-derived key would silently bind the
        # request to a different turn after a subject switch.
        return []

    trace_id = case_id.removeprefix("sc-")
    cached = [
        row for row in get_cached_trace_events(trace_id)
        if _cached_row_matches_tenant(row, tenant_id)
        and _payload_matches_case(row, case_id)
    ]
    if cached:
        return cached
    try:
        exact = db.execute(text(
            "SELECT trace_id, event_type, payload FROM decision_trace_events "
            "WHERE trace_id=:trace_id AND tenant_id=:tenant_id ORDER BY created_at ASC"
        ), {"trace_id": trace_id, "tenant_id": tenant_id}).mappings().all()
    except Exception:
        exact = []
    if exact:
        return [dict(row) for row in exact]

    # Compatibility for cases created by the historical timeout path, where
    # the case suffix and trace prefix differed. Keep this bounded and validate
    # the structured payload instead of trusting a text match.
    try:
        possible = db.execute(text(
            "SELECT trace_id, event_type, payload FROM decision_trace_events "
            "WHERE tenant_id=:tenant_id AND event_type='ambiguity_exploration_projected' "
            "AND CAST(payload AS TEXT) LIKE :case_marker "
            "ORDER BY created_at DESC LIMIT 25"
        ), {"tenant_id": tenant_id, "case_marker": f"%{case_id}%"}).mappings().all()
    except Exception:
        possible = []
    matched: list[dict[str, Any]] = []
    for raw in reversed(possible):
        row = dict(raw)
        if _payload_matches_case(row, case_id):
            matched.append(row)
    return matched


__all__ = ["load_case_trace_events"]
