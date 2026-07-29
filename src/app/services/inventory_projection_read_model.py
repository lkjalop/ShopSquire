"""Atomic, rebuildable read model over authoritative inventory observations."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.authoritative_business_feed import BusinessObservation
from src.app.services.inventory_event_projection import project_inventory_events


PROJECTION_VERSION = 1


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _observations(tenant_id: str, source: str) -> list[BusinessObservation]:
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT entity_type,external_id,event_time,payload_json,schema_version,
                       corrects_observation_id,reverses_observation_id
                FROM authoritative_business_observation
                WHERE tenant_id=:tenant AND source=:source
                  AND quality_status='accepted'
                ORDER BY event_time,entity_type,external_id,id
                """
            ),
            {"tenant": tenant_id, "source": source},
        ).fetchall()
    return [
        BusinessObservation(
            entity_type=str(row[0]),
            external_id=str(row[1]),
            event_time=(
                row[2].isoformat() if hasattr(row[2], "isoformat") else str(row[2])
            ),
            payload=json.loads(str(row[3])),
            schema_version=int(row[4]),
            corrects_observation_id=str(row[5]) if row[5] else None,
            reverses_observation_id=str(row[6]) if row[6] else None,
        )
        for row in rows
    ]


def rebuild_inventory_projection(
    *,
    tenant_id: str,
    source: str,
    default_location_id: str = "location:primary",
) -> dict[str, Any]:
    """Replace only the disposable scoped projection in one transaction."""
    tenant = str(tenant_id or "").strip()
    source_name = str(source or "").strip().lower()
    if not tenant or not source_name:
        raise ValueError("inventory_projection_scope_required")
    started = datetime.now(timezone.utc)
    observations = _observations(tenant, source_name)
    projected = project_inventory_events(
        observations,
        tenant_id=tenant,
        source=source_name,
        default_location_id=default_location_id,
    )
    projection_hash = hashlib.sha256(_canonical(projected).encode()).hexdigest()
    run_id = hashlib.sha256(
        f"{tenant}|{source_name}|{PROJECTION_VERSION}|{projection_hash}".encode()
    ).hexdigest()
    negatives = projected["balance_integrity"]["negative_balances"]
    mismatches = projected["atp_reconciliation"]["mismatches"]
    conservation = projected["conservation"]["internal_movement_failures"]
    status = (
        "insufficient"
        if not observations
        else "quarantined"
        if negatives or mismatches or conservation
        else "ready"
    )
    exceptions: list[tuple[str, dict[str, Any]]] = []
    if not observations:
        exceptions.append((
            "insufficient_data",
            {"reason": "no_accepted_authoritative_inventory_observations"},
        ))
    exceptions.extend(("negative_balance", row) for row in negatives)
    exceptions.extend(("atp_reconciliation", row) for row in mismatches)
    exceptions.extend(
        ("conservation_failure", {"external_id": external_id})
        for external_id in conservation
    )
    finished = datetime.now(timezone.utc)
    with db_session() as db:
        db.execute(
            text(
                """
                DELETE FROM inventory_projection_exception
                WHERE tenant_id=:tenant AND source=:source
                """
            ),
            {"tenant": tenant, "source": source_name},
        )
        db.execute(
            text(
                """
                DELETE FROM inventory_projection_balance
                WHERE tenant_id=:tenant AND source=:source
                """
            ),
            {"tenant": tenant, "source": source_name},
        )
        exists = db.execute(
            text("SELECT 1 FROM inventory_projection_run WHERE id=:id"),
            {"id": run_id},
        ).fetchone()
        if not exists:
            db.execute(
                text(
                    """
                    INSERT INTO inventory_projection_run
                    (id,tenant_id,source,projection_version,input_count,
                     projection_hash,status,started_at,finished_at)
                    VALUES
                    (:id,:tenant,:source,:version,:count,:hash,:status,:started,:finished)
                    """
                ),
                {
                    "id": run_id,
                    "tenant": tenant,
                    "source": source_name,
                    "version": PROJECTION_VERSION,
                    "count": len(observations),
                    "hash": projection_hash,
                    "status": status,
                    "started": started.isoformat(),
                    "finished": finished.isoformat(),
                },
            )
        for row in projected["balances"]:
            row_status = (
                "quarantined"
                if any(
                    item["variant_id"] == row["variant_id"]
                    and item["location_id"] == row["location_id"]
                    and item["uom"] == row["uom"]
                    and item["custody"] == row["custody"]
                    for item in negatives
                )
                else "available"
            )
            db.execute(
                text(
                    """
                    INSERT INTO inventory_projection_balance
                    (tenant_id,source,variant_id,location_id,uom,custody,
                     quantity,status,projection_run_id)
                    VALUES
                    (:tenant,:source,:variant,:location,:uom,:custody,
                     :quantity,:status,:run_id)
                    """
                ),
                {
                    "tenant": tenant,
                    "source": source_name,
                    "variant": row["variant_id"],
                    "location": row["location_id"],
                    "uom": row["uom"],
                    "custody": row["custody"],
                    "quantity": str(row["quantity"]),
                    "status": row_status,
                    "run_id": run_id,
                },
            )
        for index, (kind, details) in enumerate(exceptions):
            exception_id = hashlib.sha256(
                f"{run_id}|{kind}|{index}|{_canonical(details)}".encode()
            ).hexdigest()
            db.execute(
                text(
                    """
                    INSERT INTO inventory_projection_exception
                    (id,tenant_id,source,projection_run_id,exception_type,
                     observation_id,details_json,created_at)
                    VALUES
                    (:id,:tenant,:source,:run_id,:kind,:observation_id,
                     :details,:created_at)
                    """
                ),
                {
                    "id": exception_id,
                    "tenant": tenant,
                    "source": source_name,
                    "run_id": run_id,
                    "kind": kind,
                    "observation_id": details.get("observation_id"),
                    "details": _canonical(details),
                    "created_at": finished.isoformat(),
                },
            )
        db.commit()
    return {
        "run_id": run_id,
        "tenant_id": tenant,
        "source": source_name,
        "status": status,
        "projection_hash": projection_hash,
        "input_count": len(observations),
        "balance_count": len(projected["balances"]),
        "exception_count": len(exceptions),
        "execution_allowed": status == "ready",
    }


def inventory_projection_rows(
    *, tenant_id: str, source: str
) -> list[dict[str, Any]]:
    with db_session() as db:
        rows = db.execute(
            text(
                """
                SELECT variant_id,location_id,uom,custody,quantity,status,
                       projection_run_id
                FROM inventory_projection_balance
                WHERE tenant_id=:tenant AND source=:source
                ORDER BY variant_id,location_id,uom,custody
                """
            ),
            {
                "tenant": str(tenant_id or "").strip(),
                "source": str(source or "").strip().lower(),
            },
        ).fetchall()
    return [
        {
            "variant_id": str(row[0]),
            "location_id": str(row[1]),
            "uom": str(row[2]),
            "custody": str(row[3]),
            "quantity": str(row[4]),
            "status": str(row[5]),
            "projection_run_id": str(row[6]),
        }
        for row in rows
    ]


def inventory_projection_status(
    *,
    tenant_id: str,
    source: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Return bounded projection/run/exception evidence for an operator."""
    tenant = str(tenant_id or "").strip()
    source_name = str(source or "").strip().lower()
    if not tenant:
        raise ValueError("inventory_projection_tenant_required")
    capped = max(1, min(int(limit), 200))
    source_clause = " AND source=:source" if source_name else ""
    params: dict[str, Any] = {"tenant": tenant, "limit": capped}
    if source_name:
        params["source"] = source_name
    with db_session() as db:
        runs = db.execute(
            text(
                f"""
                SELECT id,source,projection_version,input_count,projection_hash,
                       status,started_at,finished_at
                FROM inventory_projection_run
                WHERE tenant_id=:tenant{source_clause}
                ORDER BY finished_at DESC,id DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        exceptions = db.execute(
            text(
                f"""
                SELECT id,source,projection_run_id,exception_type,observation_id,
                       details_json,created_at
                FROM inventory_projection_exception
                WHERE tenant_id=:tenant{source_clause}
                ORDER BY created_at DESC,id DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
        balances = db.execute(
            text(
                f"""
                SELECT source,status,COUNT(*) AS row_count
                FROM inventory_projection_balance
                WHERE tenant_id=:tenant{source_clause}
                GROUP BY source,status
                ORDER BY source,status
                """
            ),
            {key: value for key, value in params.items() if key != "limit"},
        ).mappings().all()
    return {
        "tenant_id": tenant,
        "source": source_name or None,
        "runs": [
            {
                **dict(row),
                "id": str(row["id"]),
                "projection_hash": str(row["projection_hash"]),
                "started_at": str(row["started_at"]),
                "finished_at": str(row["finished_at"]),
            }
            for row in runs
        ],
        "exceptions": [
            {
                **dict(row),
                "id": str(row["id"]),
                "projection_run_id": str(row["projection_run_id"]),
                "details": json.loads(str(row["details_json"])),
                "created_at": str(row["created_at"]),
            }
            for row in exceptions
        ],
        "balance_summary": [dict(row) for row in balances],
        "execution_policy": {
            "ready_required": True,
            "quarantined_projection_can_execute": False,
            "hidden_compensation_allowed": False,
        },
    }
