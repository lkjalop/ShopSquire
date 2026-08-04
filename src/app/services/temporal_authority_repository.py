"""Persistence boundary for versioned operational calendars and response expectations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import inspect, text

from src.app.services.temporal_authority import (
    CalendarException,
    OperationalCalendar,
    OperationalInterval,
    ResponsePolicy,
    evaluate_response_expectation,
)


def _id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _utc(value: datetime | str) -> datetime:
    parsed = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    )
    if parsed.tzinfo is None:
        raise ValueError("timezone_aware_repository_instant_required")
    return parsed.astimezone(timezone.utc)


def _tables(db) -> set[str]:
    return set(inspect(db.connection()).get_table_names())


def persist_operational_calendar(
    db,
    *,
    tenant_id: str,
    calendar: OperationalCalendar,
    source_ref: str,
    source_version: str,
    observed_at: datetime | str,
    expires_at: datetime | str,
    effective_from: datetime | str,
) -> dict[str, Any]:
    observed = _utc(observed_at)
    expires = _utc(expires_at)
    effective = _utc(effective_from)
    if expires <= observed:
        raise ValueError("calendar_expiry_must_follow_observation")
    calendar_id = _id(
        tenant_id,
        calendar.owner_type,
        calendar.owner_ref,
        calendar.version,
    )
    now = datetime.now(timezone.utc).isoformat()
    previous = db.execute(
        text(
            "SELECT id,calendar_version FROM operational_calendar WHERE tenant_id=:tenant "
            "AND owner_type=:owner_type AND owner_ref=:owner_ref AND status='active' "
            "AND calendar_version<>:version ORDER BY effective_from DESC LIMIT 1"
        ),
        {
            "tenant": tenant_id,
            "owner_type": calendar.owner_type,
            "owner_ref": calendar.owner_ref,
            "version": calendar.version,
        },
    ).fetchone()
    db.execute(
        text(
            "UPDATE operational_calendar SET status='superseded' "
            "WHERE tenant_id=:tenant AND owner_type=:owner_type AND owner_ref=:owner_ref "
            "AND status='active' AND calendar_version<>:version"
        ),
        {
            "tenant": tenant_id,
            "owner_type": calendar.owner_type,
            "owner_ref": calendar.owner_ref,
            "version": calendar.version,
        },
    )
    inserted = db.execute(
        text(
            "INSERT INTO operational_calendar "
            "(id,tenant_id,owner_type,owner_ref,timezone_name,calendar_version,authority,source_ref,"
            "source_version,observed_at,expires_at,effective_from,status,created_at) VALUES "
            "(:id,:tenant,:owner_type,:owner_ref,:timezone,:version,:authority,:source_ref,"
            ":source_version,:observed,:expires,:effective,'active',:created) ON CONFLICT DO NOTHING"
        ),
        {
            "id": calendar_id,
            "tenant": tenant_id,
            "owner_type": calendar.owner_type,
            "owner_ref": calendar.owner_ref,
            "timezone": calendar.timezone_name,
            "version": calendar.version,
            "authority": calendar.authority,
            "source_ref": source_ref,
            "source_version": source_version,
            "observed": observed.isoformat(),
            "expires": expires.isoformat(),
            "effective": effective.isoformat(),
            "created": now,
        },
    )
    for item in calendar.weekly_intervals:
        interval_id = _id(
            calendar_id, str(item.weekday), item.start_local.isoformat(), item.end_local.isoformat()
        )
        db.execute(
            text(
                "INSERT INTO operational_calendar_interval "
                "(id,calendar_id,weekday,start_local,end_local) VALUES "
                "(:id,:calendar,:weekday,:start,:end) ON CONFLICT DO NOTHING"
            ),
            {
                "id": interval_id,
                "calendar": calendar_id,
                "weekday": item.weekday,
                "start": item.start_local.isoformat(),
                "end": item.end_local.isoformat(),
            },
        )
    for item in calendar.exceptions:
        exception_id = _id(calendar_id, item.local_date.isoformat())
        intervals_json = json.dumps(
            [
                {"start_local": start.isoformat(), "end_local": end.isoformat()}
                for start, end in item.intervals
            ],
            sort_keys=True,
            separators=(",", ":"),
        )
        db.execute(
            text(
                "INSERT INTO operational_calendar_exception "
                "(id,calendar_id,local_date,closed,intervals_json,reason) VALUES "
                "(:id,:calendar,:local_date,:closed,:intervals,:reason) ON CONFLICT DO NOTHING"
            ),
            {
                "id": exception_id,
                "calendar": calendar_id,
                "local_date": item.local_date.isoformat(),
                "closed": bool(item.closed),
                "intervals": intervals_json,
                "reason": None,
            },
        )
    invalidation = None
    if previous is not None and "temporal_dependency" in _tables(db):
        from src.app.services.temporal_invalidation import invalidate_source_dependencies

        invalidation = invalidate_source_dependencies(
            db,
            tenant_id=tenant_id,
            source_type="operational_calendar",
            source_id=str(previous[0]),
            source_version=str(previous[1]),
            reason=f"superseded_by_calendar:{calendar.version}",
        )
    return {
        "id": calendar_id,
        "calendar_version": calendar.version,
        "status": "active",
        "idempotent": inserted.rowcount == 0,
        "invalidation": invalidation,
    }


def persist_supplier_response_policy(
    db,
    *,
    tenant_id: str,
    supplier_id: str,
    supplier_facility_id: str,
    channel: str,
    calendar_id: str,
    policy: ResponsePolicy,
    effective_from: datetime | str,
) -> dict[str, Any]:
    effective = _utc(effective_from)
    policy_id = _id(tenant_id, supplier_id, supplier_facility_id, channel, policy.version)
    previous = db.execute(
        text(
            "SELECT policy_version FROM supplier_response_policy WHERE tenant_id=:tenant "
            "AND supplier_id=:supplier AND supplier_facility_id=:facility AND channel=:channel "
            "AND status='active' AND policy_version<>:version ORDER BY effective_from DESC LIMIT 1"
        ),
        {
            "tenant": tenant_id,
            "supplier": supplier_id,
            "facility": supplier_facility_id,
            "channel": channel,
            "version": policy.version,
        },
    ).fetchone()
    db.execute(
        text(
            "UPDATE supplier_response_policy SET status='superseded' WHERE tenant_id=:tenant "
            "AND supplier_id=:supplier AND supplier_facility_id=:facility AND channel=:channel "
            "AND status='active' AND policy_version<>:version"
        ),
        {
            "tenant": tenant_id,
            "supplier": supplier_id,
            "facility": supplier_facility_id,
            "channel": channel,
            "version": policy.version,
        },
    )
    result = db.execute(
        text(
            "INSERT INTO supplier_response_policy "
            "(id,tenant_id,supplier_id,supplier_facility_id,channel,calendar_id,policy_version,"
            "acknowledgement_business_seconds,quote_business_seconds,human_decision_business_seconds,"
            "transmit_outside_hours,effective_from,status,created_at) VALUES "
            "(:id,:tenant,:supplier,:facility,:channel,:calendar,:version,:ack,:quote,:human,:transmit,"
            ":effective,'active',:created) ON CONFLICT DO NOTHING"
        ),
        {
            "id": policy_id,
            "tenant": tenant_id,
            "supplier": supplier_id,
            "facility": supplier_facility_id,
            "channel": channel,
            "calendar": calendar_id,
            "version": policy.version,
            "ack": policy.acknowledgement_business_seconds,
            "quote": policy.quote_business_seconds,
            "human": policy.human_decision_business_seconds or policy.quote_business_seconds,
            "transmit": policy.transmit_outside_hours,
            "effective": effective.isoformat(),
            "created": datetime.now(timezone.utc).isoformat(),
        },
    )
    invalidation = None
    if previous is not None and "temporal_dependency" in _tables(db):
        from src.app.services.temporal_invalidation import invalidate_source_dependencies

        invalidation = invalidate_source_dependencies(
            db,
            tenant_id=tenant_id,
            source_type="supplier_response_policy",
            source_id=f"{supplier_id}:{supplier_facility_id}:{channel}",
            source_version=str(previous[0]),
            reason=f"superseded_by_policy:{policy.version}",
        )
    return {
        "id": policy_id,
        "policy_version": policy.version,
        "status": "active",
        "idempotent": result.rowcount == 0,
        "invalidation": invalidation,
    }


def supplier_response_expectation(
    db,
    *,
    tenant_id: str,
    supplier_id: str,
    supplier_facility_id: str,
    channel: str = "email",
    submitted_at: datetime | None = None,
) -> dict[str, Any]:
    required = {
        "operational_calendar",
        "operational_calendar_interval",
        "operational_calendar_exception",
        "supplier_response_policy",
    }
    if not required.issubset(_tables(db)):
        return {
            "calendar_state": "unknown",
            "sla_clock": "unknown",
            "reason": "temporal_authority_schema_unavailable",
            "freshness": "missing",
        }
    now = _utc(submitted_at or datetime.now(timezone.utc))
    row = db.execute(
        text(
            "SELECT p.policy_version,p.acknowledgement_business_seconds,p.quote_business_seconds,"
            "p.human_decision_business_seconds,p.transmit_outside_hours,c.id,c.owner_type,c.owner_ref,"
            "c.timezone_name,c.calendar_version,c.authority,c.expires_at "
            "FROM supplier_response_policy p JOIN operational_calendar c ON c.id=p.calendar_id "
            "WHERE p.tenant_id=:tenant AND p.supplier_id=:supplier AND p.supplier_facility_id=:facility "
            "AND p.channel=:channel AND p.status='active' AND c.status='active' "
            "AND p.effective_from<=:now AND c.effective_from<=:now "
            "ORDER BY p.effective_from DESC,p.created_at DESC LIMIT 1"
        ),
        {
            "tenant": tenant_id,
            "supplier": supplier_id,
            "facility": supplier_facility_id,
            "channel": channel,
            "now": now.isoformat(),
        },
    ).fetchone()
    if row is None:
        return {
            "calendar_state": "unknown",
            "sla_clock": "unknown",
            "reason": "supplier_response_policy_missing",
            "freshness": "missing",
        }
    intervals = db.execute(
        text(
            "SELECT weekday,start_local,end_local FROM operational_calendar_interval "
            "WHERE calendar_id=:calendar ORDER BY weekday,start_local"
        ),
        {"calendar": str(row[5])},
    ).fetchall()
    exceptions = db.execute(
        text(
            "SELECT local_date,closed,intervals_json FROM operational_calendar_exception "
            "WHERE calendar_id=:calendar ORDER BY local_date"
        ),
        {"calendar": str(row[5])},
    ).fetchall()
    expiry = _utc(str(row[11]))
    calendar = OperationalCalendar(
        calendar_id=str(row[5]),
        owner_type=str(row[6]),
        owner_ref=str(row[7]),
        timezone_name=str(row[8]),
        weekly_intervals=tuple(
            OperationalInterval(
                weekday=int(item[0]),
                start_local=time.fromisoformat(str(item[1])),
                end_local=time.fromisoformat(str(item[2])),
            )
            for item in intervals
        ),
        exceptions=tuple(
            CalendarException(
                local_date=datetime.fromisoformat(str(item[0])).date(),
                closed=bool(item[1]),
                intervals=tuple(
                    (
                        time.fromisoformat(str(value["start_local"])),
                        time.fromisoformat(str(value["end_local"])),
                    )
                    for value in json.loads(str(item[2] or "[]"))
                ),
            )
            for item in exceptions
        ),
        version=str(row[9]),
        authority=str(row[10]),
        freshness="current" if expiry > now else "stale",
    )
    policy = ResponsePolicy(
        version=str(row[0]),
        acknowledgement_business_seconds=int(row[1]),
        quote_business_seconds=int(row[2]),
        human_decision_business_seconds=int(row[3]),
        transmit_outside_hours=bool(row[4]),
    )
    return evaluate_response_expectation(calendar=calendar, policy=policy, submitted_at=now)


def record_temporal_expectation(
    db,
    *,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    channel: str,
    submitted_at: datetime | str,
    expectation: dict[str, Any],
) -> dict[str, Any]:
    """Seal the exact calendar/policy result used for a communication decision."""
    submitted = _utc(submitted_at)
    policy_version = str(expectation.get("policy_version") or "unknown")
    identity = _id(tenant_id, subject_type, subject_id, policy_version, submitted.isoformat())
    dependencies = {
        "calendar_id": expectation.get("calendar_id"),
        "calendar_version": expectation.get("calendar_version"),
        "calendar_authority": expectation.get("calendar_authority"),
        "policy_version": policy_version,
        "freshness": expectation.get("freshness"),
    }
    result = db.execute(
        text(
            "INSERT INTO temporal_expectation "
            "(id,tenant_id,subject_type,subject_id,channel,calendar_id,calendar_version,policy_version,"
            "submitted_at,calendar_state,sla_clock,transmission_state,next_open_at,acknowledgement_due_at,"
            "quote_due_at,human_decision_due_at,dependencies_json,status,calculated_at) VALUES "
            "(:id,:tenant,:subject_type,:subject_id,:channel,:calendar_id,:calendar_version,:policy_version,"
            ":submitted,:calendar_state,:sla_clock,:transmission_state,:next_open,:ack_due,:quote_due,"
            ":human_due,:dependencies,'active',:calculated) ON CONFLICT DO NOTHING"
        ),
        {
            "id": identity,
            "tenant": tenant_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "channel": channel,
            "calendar_id": expectation.get("calendar_id"),
            "calendar_version": expectation.get("calendar_version"),
            "policy_version": policy_version,
            "submitted": submitted.isoformat(),
            "calendar_state": str(expectation.get("calendar_state") or "unknown"),
            "sla_clock": str(expectation.get("sla_clock") or "unknown"),
            "transmission_state": str(expectation.get("transmission_state") or "blocked_unknown"),
            "next_open": expectation.get("next_open_at"),
            "ack_due": expectation.get("acknowledgement_due_at"),
            "quote_due": expectation.get("quote_due_at"),
            "human_due": expectation.get("human_decision_due_at"),
            "dependencies": json.dumps(dependencies, sort_keys=True, separators=(",", ":")),
            "calculated": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {
        "id": identity,
        "status": "active",
        "idempotent": result.rowcount == 0,
        "dependencies": dependencies,
    }


def record_promise_calculation(
    db,
    *,
    tenant_id: str,
    case_id: str,
    option_id: str,
    result: dict[str, Any],
    calculated_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Persist a bitemporal-friendly, immutable promise feasibility result."""
    version = str(result.get("calculation_version") or "promise-feasibility-v1")
    identity = _id(tenant_id, case_id, option_id, version)
    db.execute(
        text(
            "UPDATE promise_calculation SET status='superseded' WHERE tenant_id=:tenant "
            "AND case_id=:case_id AND option_id=:option_id AND status='active' "
            "AND calculation_version<>:version"
        ),
        {"tenant": tenant_id, "case_id": case_id, "option_id": option_id, "version": version},
    )
    inserted = db.execute(
        text(
            "INSERT INTO promise_calculation "
            "(id,tenant_id,case_id,option_id,calculation_version,requested_quantity,requested_arrival_at,"
            "feasibility,confirmed_quantity,unknown_quantity,quantity_by_deadline,latest_viable_response_at,"
            "earliest_arrival_at,latest_arrival_at,carrier_cutoff_at,dispatch_ready_at,evaluated_at,"
            "response_expectation_json,reason_codes_json,"
            "dependencies_json,status,calculated_at) VALUES "
            "(:id,:tenant,:case_id,:option_id,:version,:requested,:arrival,:feasibility,:confirmed,:unknown,"
            ":quantity_by_deadline,:latest,:earliest_arrival,:latest_arrival,:carrier_cutoff,:dispatch_ready,"
            ":evaluated,:response_expectation,:reasons,:dependencies,'active',:calculated) ON CONFLICT DO NOTHING"
        ),
        {
            "id": identity,
            "tenant": tenant_id,
            "case_id": case_id,
            "option_id": option_id,
            "version": version,
            "requested": int(result.get("requested_quantity") or 0),
            "arrival": str(result.get("requested_arrival_at") or ""),
            "feasibility": str(result.get("feasibility") or "unknown"),
            "confirmed": int(
                result.get("confirmed_quantity")
                or result.get("quantity_confirmed_by_deadline")
                or 0
            ),
            "unknown": int(result.get("unknown_quantity") or 0),
            "quantity_by_deadline": int(
                result.get("quantity_by_deadline")
                or result.get("quantity_confirmed_by_deadline")
                or 0
            ),
            "latest": result.get("latest_viable_supplier_response_at")
            or result.get("latest_viable_response_at"),
            "earliest_arrival": (result.get("earliest_arrival_range") or {}).get("earliest"),
            "latest_arrival": (result.get("earliest_arrival_range") or {}).get("latest"),
            "carrier_cutoff": result.get("carrier_cutoff_at"),
            "dispatch_ready": result.get("dispatch_ready_at"),
            "evaluated": str(
                result.get("evaluated_at")
                or _utc(calculated_at or datetime.now(timezone.utc)).isoformat()
            ),
            "response_expectation": json.dumps(
                result.get("response_expectation") or {}, sort_keys=True, separators=(",", ":")
            ),
            "reasons": json.dumps(
                result.get("reason_codes") or [], sort_keys=True, separators=(",", ":")
            ),
            "dependencies": json.dumps(
                result.get("dependencies") or result.get("dependency_versions") or {},
                sort_keys=True,
                separators=(",", ":"),
            ),
            "calculated": _utc(calculated_at or datetime.now(timezone.utc)).isoformat(),
        },
    )
    if "promise_dependency" in _tables(db):
        dependencies = result.get("dependency_versions") or result.get("dependencies") or {}
        created = _utc(calculated_at or datetime.now(timezone.utc)).isoformat()
        for dependency_type, raw in sorted(dict(dependencies).items()):
            if isinstance(raw, dict):
                dependency_id = str(raw.get("id") or dependency_type)
                dependency_version = str(raw.get("version") or "unknown")
                observed_at = raw.get("observed_at")
                effective_at = raw.get("effective_at")
            else:
                dependency_id = str(dependency_type)
                dependency_version = str(raw)
                observed_at = None
                effective_at = None
            dependency_pk = _id(identity, str(dependency_type), dependency_id, dependency_version)
            db.execute(
                text(
                    "INSERT INTO promise_dependency "
                    "(id,promise_calculation_id,dependency_type,dependency_id,dependency_version,"
                    "observed_at,effective_at,created_at) VALUES "
                    "(:id,:calculation,:type,:dependency,:version,:observed,:effective,:created) "
                    "ON CONFLICT DO NOTHING"
                ),
                {
                    "id": dependency_pk,
                    "calculation": identity,
                    "type": str(dependency_type),
                    "dependency": dependency_id,
                    "version": dependency_version,
                    "observed": observed_at,
                    "effective": effective_at,
                    "created": created,
                },
            )
            if "temporal_dependency" in _tables(db):
                from src.app.services.temporal_invalidation import register_derived_dependency

                register_derived_dependency(
                    db,
                    tenant_id=tenant_id,
                    source_type=str(dependency_type),
                    source_id=dependency_id,
                    source_version=dependency_version,
                    derived_type="buyer_supply_promise",
                    derived_id=identity,
                )
    return {
        "id": identity,
        "status": "active",
        "idempotent": inserted.rowcount == 0,
        "calculation_version": version,
    }


def supersede_case_promise_calculations(
    db,
    *,
    tenant_id: str,
    case_id: str,
    reason: str,
    superseded_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Retire current promise projections without deleting historical evidence."""
    changed = db.execute(
        text(
            "UPDATE promise_calculation SET status='superseded' "
            "WHERE tenant_id=:tenant AND case_id=:case_id AND status='active'"
        ),
        {"tenant": tenant_id, "case_id": case_id},
    ).rowcount
    if "temporal_dependency" in _tables(db):
        from src.app.services.temporal_invalidation import invalidate_derived_dependencies

        invalidate_derived_dependencies(
            db,
            tenant_id=tenant_id,
            source_type="fulfillment_case",
            source_id=case_id,
            source_version="current",
            reason=reason,
            observed_at=_utc(superseded_at or datetime.now(timezone.utc)).isoformat(),
        )
    return {"case_id": case_id, "superseded": int(changed or 0), "reason": reason}
