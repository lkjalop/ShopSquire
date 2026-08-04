"""Idempotent adapters from domain records to the canonical escalation lifecycle."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import inspect, text

from src.app.services.case_escalation import request_escalation


SOURCE_KINDS = frozenset({"procurement_room", "security_incident", "ticket"})


def _projection_id(tenant_id: str, source_kind: str, source_id: str) -> str:
    material = "\x1f".join((str(tenant_id), str(source_kind), str(source_id)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def project_escalation_source(
    db,
    *,
    tenant_id: str,
    source_kind: str,
    source_id: str,
    source_version: str,
    domain: str,
    case_id: str,
    party_ref: str | None,
    priority: str,
    reason_code: str,
    trace_id: str | None,
    evidence_refs: list[str],
    policy_version: str,
    required_response_at: str | None,
    actor_id: str,
    now_iso: str | None = None,
) -> dict[str, Any]:
    """Link a domain-owned record without making it a second lifecycle authority."""
    tenant = str(tenant_id or "").strip()
    kind = str(source_kind or "").strip()
    source = str(source_id or "").strip()
    version = str(source_version or "").strip()
    if not tenant or not source or not version:
        raise ValueError("escalation_projection_scope_required")
    if kind not in SOURCE_KINDS:
        raise ValueError("unsupported_escalation_projection_kind")

    existing = db.execute(
        text(
            "SELECT escalation_id,source_version FROM case_escalation_projection "
            "WHERE tenant_id=:tenant AND source_kind=:kind AND source_id=:source"
        ),
        {"tenant": tenant, "kind": kind, "source": source},
    ).first()
    if existing:
        if str(existing[1]) != version:
            raise ValueError("escalation_projection_version_conflict")
        return {
            "escalation_id": str(existing[0]),
            "source_kind": kind,
            "source_id": source,
            "idempotent": True,
        }

    requested = request_escalation(
        db,
        tenant_id=tenant,
        domain=domain,
        case_id=case_id,
        party_ref=party_ref,
        priority=priority,
        reason_code=reason_code,
        triggering_observation_ref=f"{kind}/{source}@{version}",
        trace_id=trace_id,
        evidence_refs=[*evidence_refs, f"{kind}/{source}@{version}"],
        policy_version=policy_version,
        required_response_at=required_response_at,
        dedupe_key=f"projection:{kind}:{source}",
        actor_id=actor_id,
        idempotency_key=f"projection:{kind}:{source}:{version}",
        ticket_id=source if kind == "ticket" else None,
        now_iso=now_iso,
    )
    projected_at = str(now_iso or "") or db.execute(
        text("SELECT updated_at FROM case_escalation WHERE id=:id"),
        {"id": requested["escalation_id"]},
    ).scalar_one()
    db.execute(
        text(
            "INSERT INTO case_escalation_projection "
            "(id,escalation_id,tenant_id,source_kind,source_id,source_version,projected_at) "
            "VALUES (:id,:escalation,:tenant,:kind,:source,:version,:projected)"
        ),
        {
            "id": _projection_id(tenant, kind, source),
            "escalation": requested["escalation_id"],
            "tenant": tenant,
            "kind": kind,
            "source": source,
            "version": version,
            "projected": projected_at,
        },
    )
    db.commit()
    return {
        "escalation_id": requested["escalation_id"],
        "source_kind": kind,
        "source_id": source,
        "idempotent": False,
    }


def list_escalation_projections(
    db, *, tenant_id: str, escalation_id: str
) -> list[dict[str, str]]:
    rows = db.execute(
        text(
            "SELECT source_kind,source_id,source_version,projected_at "
            "FROM case_escalation_projection "
            "WHERE tenant_id=:tenant AND escalation_id=:escalation "
            "ORDER BY projected_at,source_kind,source_id"
        ),
        {"tenant": str(tenant_id), "escalation": str(escalation_id)},
    ).fetchall()
    return [
        {
            "source_kind": str(row[0]),
            "source_id": str(row[1]),
            "source_version": str(row[2]),
            "projected_at": str(row[3]),
        }
        for row in rows
    ]


def project_existing_escalation_sources(
    db, *, tenant_id: str, actor_id: str, now_iso: str | None = None
) -> dict[str, Any]:
    """Project only records with authoritative tenant ownership; report unsafe legacy rows."""
    tenant = str(tenant_id or "").strip()
    if not tenant:
        raise ValueError("authoritative_tenant_required")
    tables = set(inspect(db.connection()).get_table_names())
    projected: list[dict[str, Any]] = []
    conflicts: list[dict[str, str]] = []
    unowned = 0

    def _apply(**values: Any) -> None:
        try:
            projected.append(
                project_escalation_source(
                    db, tenant_id=tenant, actor_id=actor_id, now_iso=now_iso, **values
                )
            )
        except ValueError as exc:
            conflicts.append({
                "source_kind": str(values["source_kind"]),
                "source_id": str(values["source_id"]),
                "reason": str(exc),
            })

    if "procurement_human_room" in tables:
        rows = db.execute(text(
            "SELECT id,case_id,version,requested_at FROM procurement_human_room "
            "WHERE tenant_id=:tenant ORDER BY requested_at,id"
        ), {"tenant": tenant}).fetchall()
        for row in rows:
            _apply(
                source_kind="procurement_room", source_id=str(row[0]),
                source_version=str(row[2]), domain="procurement", case_id=str(row[1]),
                party_ref=None, priority="high", reason_code="clarification_required",
                trace_id=None, evidence_refs=[], policy_version="escalation-projection-v1",
                required_response_at=None,
            )

    if "tickets" in tables:
        unowned += int(db.execute(text(
            "SELECT COUNT(*) FROM tickets WHERE tenant_id IS NULL OR tenant_id=''"
        )).scalar() or 0)
        rows = db.execute(text(
            "SELECT id,trace_id,severity,COALESCE(updated_at,created_at),evidence "
            "FROM tickets WHERE tenant_id=:tenant ORDER BY created_at,id"
        ), {"tenant": tenant}).fetchall()
        for row in rows:
            severity = str(row[2] or "medium").lower()
            _apply(
                source_kind="ticket", source_id=str(row[0]), source_version=str(row[3] or "1"),
                domain="security", case_id=str(row[1] or f"ticket:{row[0]}"), party_ref=None,
                priority=severity if severity in {"low", "medium", "high", "critical"} else "medium",
                reason_code="system_degraded", trace_id=str(row[1] or "") or None,
                evidence_refs=[f"ticket-evidence/{row[0]}" if row[4] else ""],
                policy_version="escalation-projection-v1", required_response_at=None,
            )

    if "incidents" in tables:
        columns = {item["name"] for item in inspect(db.connection()).get_columns("incidents")}
        if {"tenant_id", "case_id", "trace_id"}.issubset(columns):
            unowned += int(db.execute(text(
                "SELECT COUNT(*) FROM incidents WHERE tenant_id IS NULL OR tenant_id=''"
            )).scalar() or 0)
            rows = db.execute(text(
                "SELECT id,case_id,trace_id,event_id,severity,created_at FROM incidents "
                "WHERE tenant_id=:tenant ORDER BY created_at,id"
            ), {"tenant": tenant}).fetchall()
            for row in rows:
                severity = str(row[4] or "high").lower()
                _apply(
                    source_kind="security_incident", source_id=str(row[0]),
                    source_version=str(row[5] or "1"), domain="security",
                    case_id=str(row[1] or row[2] or row[3] or f"incident:{row[0]}"),
                    party_ref=None,
                    priority=severity if severity in {"low", "medium", "high", "critical"} else "high",
                    reason_code="security_quarantine", trace_id=str(row[2] or row[3] or "") or None,
                    evidence_refs=[f"security-incident/{row[0]}"],
                    policy_version="escalation-projection-v1", required_response_at=None,
                )

    return {
        "tenant_id": tenant,
        "projected_count": len(projected),
        "idempotent_count": sum(1 for item in projected if item.get("idempotent")),
        "unowned_legacy_count": unowned,
        "conflicts": conflicts,
        "status": "needs_ownership_classification" if unowned else "complete",
    }
