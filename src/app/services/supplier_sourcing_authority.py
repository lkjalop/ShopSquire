"""Tenant-scoped supplier sourcing policy and queue observations.

The core stores only supplier/facility identities, numeric envelopes, time and evidence
health. Portal, EDI, email, ERP and category-specific interpretation belongs in adapters.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from sqlalchemy import text

from src.app.services.sourcing_backpressure import (
    SourcingBackpressurePolicy,
    SourcingQueueState,
)
from src.app.services.operational_tool_scope import operational_read_receipt
from src.app.services.temporal_authority_repository import supplier_response_expectation
from src.app.services.tool_capability_selector import ToolCapability


def _utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stamp(value: datetime | str) -> str:
    parsed = _utc(value)
    if parsed is None:  # pragma: no cover - guarded by the signature
        raise ValueError("timestamp_required")
    return parsed.isoformat()


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def persist_sourcing_policy(
    db,
    *,
    tenant_id: str,
    supplier_id: str,
    supplier_facility_id: str,
    policy_version: str,
    max_open_requests: int,
    max_open_units: int,
    max_request_units: int,
    max_dispatches_per_hour: int,
    acknowledgement_sla_seconds: int,
    effective_from: datetime | str,
) -> dict[str, Any]:
    limits = {
        "max_open_requests": int(max_open_requests),
        "max_open_units": int(max_open_units),
        "max_request_units": int(max_request_units),
        "max_dispatches_per_hour": int(max_dispatches_per_hour),
        "acknowledgement_sla_seconds": int(acknowledgement_sla_seconds),
    }
    if any(value <= 0 for value in limits.values()):
        raise ValueError("supplier_sourcing_policy_limits_must_be_positive")
    identity = [tenant_id, supplier_id, supplier_facility_id, policy_version]
    policy_id = _stable_id(*identity)
    now = datetime.now(timezone.utc).isoformat()
    db.execute(text(
        "UPDATE supplier_sourcing_policy SET status='superseded' "
        "WHERE tenant_id=:tenant AND supplier_id=:supplier AND supplier_facility_id=:facility "
        "AND status='active' AND policy_version<>:version"
    ), {"tenant": tenant_id, "supplier": supplier_id, "facility": supplier_facility_id,
        "version": policy_version})
    result = db.execute(text(
        "INSERT INTO supplier_sourcing_policy "
        "(id,tenant_id,supplier_id,supplier_facility_id,policy_version,max_open_requests," 
        "max_open_units,max_request_units,max_dispatches_per_hour,acknowledgement_sla_seconds," 
        "effective_from,status,created_at) VALUES "
        "(:id,:tenant,:supplier,:facility,:version,:requests,:units,:request_units,:dispatches," 
        ":sla,:effective,'active',:created) ON CONFLICT DO NOTHING"
    ), {"id": policy_id, "tenant": tenant_id, "supplier": supplier_id,
        "facility": supplier_facility_id, "version": policy_version,
        "requests": limits["max_open_requests"], "units": limits["max_open_units"],
        "request_units": limits["max_request_units"],
        "dispatches": limits["max_dispatches_per_hour"],
        "sla": limits["acknowledgement_sla_seconds"],
        "effective": _stamp(effective_from), "created": now})
    return {"id": policy_id, "status": "active", "idempotent": result.rowcount == 0,
            "policy_version": policy_version, **limits}


def record_sourcing_queue_observation(
    db,
    *,
    tenant_id: str,
    supplier_id: str,
    supplier_facility_id: str,
    source_id: str,
    source_version: str,
    observed_at: datetime | str,
    expires_at: datetime | str,
    open_requests: int,
    open_units: int,
    dispatches_last_hour: int,
    oldest_unacknowledged_at: datetime | str | None = None,
) -> dict[str, Any]:
    counts = [int(open_requests), int(open_units), int(dispatches_last_hour)]
    if min(counts) < 0:
        raise ValueError("supplier_queue_counts_cannot_be_negative")
    observed = _utc(observed_at)
    expires = _utc(expires_at)
    oldest = _utc(oldest_unacknowledged_at)
    if observed is None or expires is None or expires <= observed:
        raise ValueError("supplier_queue_expiry_must_follow_observation")
    if oldest is not None and oldest > observed:
        raise ValueError("oldest_unacknowledged_cannot_follow_observation")
    observation_id = _stable_id(
        tenant_id, supplier_id, supplier_facility_id, source_id, source_version,
    )
    result = db.execute(text(
        "INSERT INTO supplier_sourcing_queue_observation "
        "(id,tenant_id,supplier_id,supplier_facility_id,source_id,source_version,observed_at," 
        "expires_at,open_requests,open_units,dispatches_last_hour,oldest_unacknowledged_at,created_at) "
        "VALUES (:id,:tenant,:supplier,:facility,:source,:version,:observed,:expires,:requests," 
        ":units,:dispatches,:oldest,:created) ON CONFLICT DO NOTHING"
    ), {"id": observation_id, "tenant": tenant_id, "supplier": supplier_id,
        "facility": supplier_facility_id, "source": source_id, "version": source_version,
        "observed": observed.isoformat(), "expires": expires.isoformat(),
        "requests": counts[0], "units": counts[1], "dispatches": counts[2],
        "oldest": oldest.isoformat() if oldest else None,
        "created": datetime.now(timezone.utc).isoformat()})
    return {"id": observation_id, "status": "observed", "idempotent": result.rowcount == 0,
            "source_version": source_version}


def supplier_pressure_projection(
    db,
    *,
    tenant_id: str,
    supplier_refs: Iterable[tuple[str, str]],
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    stamp = _utc(now or datetime.now(timezone.utc))
    assert stamp is not None
    output: list[dict[str, Any]] = []
    for supplier_id, facility_id in sorted(set(supplier_refs)):
        policy = db.execute(text(
            "SELECT policy_version,max_open_requests,max_open_units,max_request_units," 
            "max_dispatches_per_hour,acknowledgement_sla_seconds,effective_from "
            "FROM supplier_sourcing_policy WHERE tenant_id=:tenant AND supplier_id=:supplier "
            "AND supplier_facility_id=:facility AND status='active' AND effective_from<=:now "
            "ORDER BY effective_from DESC,created_at DESC LIMIT 1"
        ), {"tenant": tenant_id, "supplier": supplier_id, "facility": facility_id,
            "now": stamp.isoformat()}).fetchone()
        queue = db.execute(text(
            "SELECT source_id,source_version,observed_at,expires_at,open_requests,open_units," 
            "dispatches_last_hour,oldest_unacknowledged_at FROM "
            "supplier_sourcing_queue_observation WHERE tenant_id=:tenant AND supplier_id=:supplier "
            "AND supplier_facility_id=:facility AND observed_at<=:now "
            "ORDER BY observed_at DESC,created_at DESC LIMIT 1"
        ), {"tenant": tenant_id, "supplier": supplier_id, "facility": facility_id,
            "now": stamp.isoformat()}).fetchone()
        if policy is None or queue is None:
            receipt = operational_read_receipt(
                capability=ToolCapability.SUPPLIER_OFFER_READ,
                tenant_id=tenant_id,
                deployment_id=f"supplier_ledger:{supplier_id}:{facility_id}",
                enabled=False, health_status="unhealthy", authority_score=90,
            )
            output.append({
                "supplier_id": supplier_id, "supplier_facility_id": facility_id,
                "status": "degraded", "external_contact_authority": "blocked",
                "reason_codes": ["supplier_policy_missing" if policy is None else "supplier_queue_missing"],
                "source_health": {"status": "missing"},
                "tool_selection_receipt": receipt.model_dump(mode="json"),
            })
            continue
        expires = _utc(str(queue[3]))
        observed = _utc(str(queue[2]))
        oldest = _utc(queue[7])
        stale = expires is None or expires <= stamp
        queue_age = max(0, int((stamp - oldest).total_seconds())) if oldest else None
        temporal_response = (
            supplier_response_expectation(
                db, tenant_id=tenant_id, supplier_id=supplier_id,
                supplier_facility_id=facility_id, channel="email",
                submitted_at=oldest,
            ) if oldest is not None else {
                "calendar_state": "unknown", "sla_clock": "unknown",
                "reason": "no_unacknowledged_supplier_request",
            }
        )
        request_util = round(int(queue[4]) / int(policy[1]), 4)
        unit_util = round(int(queue[5]) / int(policy[2]), 4)
        dispatch_util = round(int(queue[6]) / int(policy[4]), 4)
        reasons: list[str] = []
        if int(queue[4]) >= int(policy[1]):
            reasons.append("supplier_open_request_limit")
        if int(queue[5]) >= int(policy[2]):
            reasons.append("supplier_open_unit_limit")
        if int(queue[6]) >= int(policy[4]):
            reasons.append("supplier_dispatch_rate_limit")
        acknowledgement_due = _utc(temporal_response.get("acknowledgement_due_at"))
        if acknowledgement_due is not None:
            sla_breached = stamp > acknowledgement_due
            sla_basis = "business_calendar"
        else:
            # Compatibility fallback while a tenant has not yet onboarded calendar
            # authority. The UI labels the temporal state UNKNOWN; this elapsed clock
            # must not be presented as a business-hours prediction.
            sla_breached = queue_age is not None and queue_age > int(policy[5])
            sla_basis = "elapsed_compatibility"
        if sla_breached:
            reasons.append("supplier_acknowledgement_sla_breached")
        if stale:
            status = "degraded"
        elif reasons:
            status = "blocked"
        elif max(request_util, unit_util, dispatch_util) >= 0.8:
            status = "watch"
        else:
            status = "healthy"
        receipt = operational_read_receipt(
            capability=ToolCapability.SUPPLIER_OFFER_READ,
            tenant_id=tenant_id,
            deployment_id=f"supplier_ledger:{supplier_id}:{facility_id}",
            enabled=not stale,
            freshness_state="stale" if stale else "fresh",
            health_status="degraded" if stale else "healthy",
            authority_score=90,
        )
        output.append({
            "supplier_id": supplier_id, "supplier_facility_id": facility_id,
            "status": status,
            "external_contact_authority": "blocked" if stale or reasons else "governed",
            "reason_codes": reasons if not stale else ["supplier_queue_stale", *reasons],
            "policy": {"version": str(policy[0]), "max_open_requests": int(policy[1]),
                       "max_open_units": int(policy[2]), "max_request_units": int(policy[3]),
                       "max_dispatches_per_hour": int(policy[4])},
            "queue": {"open_requests": int(queue[4]), "open_units": int(queue[5]),
                      "dispatches_last_hour": int(queue[6]),
                      "open_request_utilization": request_util,
                      "open_unit_utilization": unit_util,
                      "dispatch_utilization": dispatch_util},
            "response_sla": {"seconds": int(policy[5]), "queue_age_seconds": queue_age,
                             "status": "breached" if sla_breached else "within_sla",
                             "basis": sla_basis},
            "temporal_response": temporal_response,
            "source_health": {"status": "stale" if stale else "fresh",
                              "source_id": str(queue[0]), "source_version": str(queue[1]),
                              "observed_at": observed.isoformat() if observed else None,
                              "expires_at": expires.isoformat() if expires else None},
            "tool_selection_receipt": receipt.model_dump(mode="json"),
        })
    return output


def load_sourcing_admission_context(
    db,
    *,
    tenant_id: str,
    supplier_id: str,
    supplier_facility_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve the persisted policy and freshest queue observation for enforcement.

    Missing or stale authority fails closed.  The returned dataclasses are deliberately
    provider-neutral, so portal, EDI, ERP and communications adapters share one gate.
    """
    stamp = _utc(now or datetime.now(timezone.utc))
    assert stamp is not None
    projection = supplier_pressure_projection(
        db, tenant_id=tenant_id,
        supplier_refs=[(supplier_id, supplier_facility_id)], now=stamp,
    )[0]
    source_status = str((projection.get("source_health") or {}).get("status") or "missing")
    if source_status != "fresh" or not projection.get("policy") or not projection.get("queue"):
        return {
            "status": "degraded", "policy": None, "state": None,
            "reason_codes": list(projection.get("reason_codes") or ["supplier_authority_unavailable"]),
            "evidence": projection,
        }
    policy_row = projection["policy"]
    queue_row = projection["queue"]
    response_sla = projection["response_sla"]
    queue_age = response_sla.get("queue_age_seconds")
    oldest = stamp - timedelta(seconds=int(queue_age)) if queue_age is not None else None
    return {
        "status": "ready",
        "policy": SourcingBackpressurePolicy(
            max_open_requests=int(policy_row["max_open_requests"]),
            max_open_units=int(policy_row["max_open_units"]),
            max_request_units=int(policy_row["max_request_units"]),
            max_dispatches_per_hour=int(policy_row["max_dispatches_per_hour"]),
            acknowledgement_sla=timedelta(seconds=int(response_sla["seconds"])),
        ),
        "state": SourcingQueueState(
            open_requests=int(queue_row["open_requests"]),
            open_units=int(queue_row["open_units"]),
            dispatches_last_hour=int(queue_row["dispatches_last_hour"]),
            oldest_unacknowledged_at=oldest,
        ),
        "reason_codes": list(projection.get("reason_codes") or []),
        "evidence": projection,
    }
