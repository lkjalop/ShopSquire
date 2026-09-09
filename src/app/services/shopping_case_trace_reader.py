"""Bounded retrieval of the trace events that establish a shopping case."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from src.app.services.decision_log import get_cached_trace_events


def _payload_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _case_research_plan_from_trace(
    db, *, case_id: str, tenant_id: str, decision_trace_id: str | None = None,
):
    """Rebuild a plan only from the server-recorded ambiguity event."""

    from src.app.services.case_research_plan import build_case_research_plan
    from src.app.services.shopping_case_trace_reader import load_case_trace_events

    events = load_case_trace_events(
        db, case_id=case_id, tenant_id=tenant_id,
        decision_trace_id=decision_trace_id,
    )
    for event in reversed(events):
        if str(event.get("event_type") or "") != "ambiguity_exploration_projected":
            continue
        payload = _payload_object(event.get("payload"))
        purpose = str(payload.get("retained_purpose") or "").strip()
        recorded_plan_id = str(payload.get("research_plan_id") or "").strip()
        plan = build_case_research_plan(purpose) if purpose else None
        if plan is None and purpose and recorded_plan_id:
            plan = build_case_research_plan(purpose, allow_open_world=True)
        if plan is None or plan.plan_id != recorded_plan_id:
            return None
        return plan
    return None


def _case_catalog_candidate_set_from_trace(
    db, *, case_id: str, tenant_id: str, decision_trace_id: str | None = None,
):
    """Load the immutable catalog boundary recorded with the shopping case."""

    from src.app.services.case_catalog_candidates import CatalogCandidateSet, CatalogScope
    from src.app.services.shopping_case_trace_reader import load_case_trace_events

    events = load_case_trace_events(
        db,
        case_id=case_id,
        tenant_id=tenant_id,
        decision_trace_id=decision_trace_id,
    )
    for event in reversed(events):
        if str(event.get("event_type") or "") != "ambiguity_exploration_projected":
            continue
        raw = _payload_object(event.get("payload")).get("catalog_candidate_set")
        if isinstance(raw, dict):
            try:
                candidate_payload = dict(raw)
                # Events written before CatalogScope existed remain readable,
                # but their legacy taxonomy value is explicitly labelled as
                # recorded context rather than silently becoming new authority.
                candidate_payload.setdefault("catalog_scope", CatalogScope(
                    case_id=case_id,
                    tenant_id=tenant_id,
                    allowed_taxonomy_roots=(
                        [str(raw.get("taxonomy_handle"))]
                        if raw.get("taxonomy_handle") else []
                    ),
                    selected_taxonomy_root=(
                        str(raw.get("taxonomy_handle"))
                        if raw.get("taxonomy_handle") else None
                    ),
                    source=(
                        "validated_client_context"
                        if raw.get("taxonomy_handle") else "unresolved"
                    ),
                    confidence=0.5 if raw.get("taxonomy_handle") else 0.0,
                    client_context_disposition=(
                        "accepted" if raw.get("taxonomy_handle") else "not_supplied"
                    ),
                    client_taxonomy_handle=(
                        str(raw.get("taxonomy_handle"))
                        if raw.get("taxonomy_handle") else None
                    ),
                    reason="legacy_recorded_catalog_boundary",
                ).model_dump(mode="json"))
                return CatalogCandidateSet.model_validate(candidate_payload)
            except ValueError:
                break
    # A legacy/malformed case may continue gathering evidence, but cannot fall
    # back to the tenant-wide catalog and present that as a query-specific shelf.
    return CatalogCandidateSet(
        retained_purpose="Unresolved legacy shopping case",
        status="unresolved",
        taxonomy_source="unresolved",
        reason="case_candidate_set_not_recorded",
        catalog_scope=CatalogScope(
            case_id=case_id,
            tenant_id=tenant_id,
            allowed_taxonomy_roots=[],
            source="unresolved",
            confidence=0.0,
            client_context_disposition="not_supplied",
            reason="case_candidate_set_not_recorded",
        ),
    )


def _case_trace_has_event(
    db, *, case_id: str, tenant_id: str, event_type: str,
    decision_trace_id: str | None = None,
) -> bool:
    # Completion/idempotency is evidence too. Use the same tenant, case and
    # explicit-turn binding as plan retrieval, including the cache boundary.
    return any(
        str(row.get("event_type") or "") == event_type
        for row in load_case_trace_events(
            db, case_id=case_id, tenant_id=tenant_id,
            decision_trace_id=decision_trace_id,
        )
    )


def load_case_turn_history(db, *, tenant_id: str, case_id: str,
                          known_at: str | None = None, valid_at: str | None = None,
                          limit: int = 20) -> list[dict[str, Any]]:
    """Read immutable accepted turn projections, never reconstruct from current state.

    The caller must authorize buyer ownership. Both time cutoffs apply to the
    persisted record; a later correction cannot appear in an earlier knowledge view.
    """
    rows = db.execute(text(
        "SELECT id,proposed_value_json,observed_at,effective_at "
        "FROM conversation_case_amendment WHERE tenant_id=:tenant AND case_id=:case "
        "AND field_name='turn_read_model' AND status='accepted' "
        "AND (:known IS NULL OR observed_at<=:known) "
        "AND (:valid IS NULL OR effective_at<=:valid) "
        "ORDER BY observed_at DESC,id DESC LIMIT :limit"
    ), {"tenant": tenant_id, "case": case_id, "known": known_at, "valid": valid_at,
        "limit": max(1, min(limit, 100))}).all()
    return [{"commit_id": row[0], "read_model": json.loads(row[1]),
             "known_at": str(row[2]), "valid_at": str(row[3])} for row in reversed(rows)]


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
