"""Bounded retrieval of the trace events that establish a shopping case."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.app.services.decision_log import get_cached_trace_events


def load_case_trace_events(db, *, case_id: str, tenant_id: str) -> list[dict[str, Any]]:
    trace_id = case_id.removeprefix("sc-")
    cached = list(get_cached_trace_events(trace_id))
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
        payload = row.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        if isinstance(payload, dict) and str(payload.get("case_id") or "") == case_id:
            matched.append(row)
    return matched


__all__ = ["load_case_trace_events"]
