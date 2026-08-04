"""Governed composition of tenant-owned CSV facts into the shadow allocation pool."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.authoritative_business_feed import (
    ingest_authoritative_observations,
    load_observations_csv,
)
from src.app.services.demand_allocation import sync_authoritative_location_atp


def import_tenant_location_atp_csv(
    path: str | Path, *, tenant_id: str, source: str,
) -> dict[str, Any]:
    """Append CSV observations, then rebuild only that tenant/source ATP projection."""
    tenant = str(tenant_id or "").strip()
    source_id = str(source or "").strip().lower()
    if not tenant or not source_id:
        raise ValueError("tenant_atp_import_scope_required")
    observations = load_observations_csv(path)
    invalid = sorted({item.entity_type for item in observations if item.entity_type != "location_atp"})
    if invalid:
        raise ValueError("tenant_atp_csv_contains_non_atp_entities:" + ",".join(invalid))
    feed = ingest_authoritative_observations(
        tenant_id=tenant, source=source_id, observations=observations,
    )
    if feed["status"] == "malformed":
        return {"status": "rejected", "feed": feed, "projection": None}
    with db_session() as db:
        projection = sync_authoritative_location_atp(
            db, tenant_id=tenant, source=source_id,
        )
        db.commit()
    return {
        "status": "projected" if projection["applied"] else projection["status"],
        "tenant_id": tenant, "source": source_id,
        "feed": feed, "projection": projection,
        "execution_authority": "shadow_allocation_only",
    }


def tenant_atp_source_health(db, *, tenant_id: str, source: str) -> dict[str, Any]:
    """Return explicit feed and projection freshness; absence is never presented as zero ATP."""
    tenant = str(tenant_id or "").strip()
    source_id = str(source or "").strip().lower()
    run = db.execute(text(
        "SELECT id,status,records_seen,records_inserted,records_replayed,finished_at,error "
        "FROM authoritative_feed_run WHERE tenant_id=:t AND source=:s "
        "ORDER BY started_at DESC LIMIT 1"
    ), {"t": tenant, "s": source_id}).fetchone()
    snapshots = db.execute(text(
        "SELECT COUNT(*),MAX(observed_at),MIN(expires_at) FROM supply_allocation_pool "
        "WHERE tenant_id=:t AND source_id=:s"
    ), {"t": tenant, "s": source_id}).fetchone()
    now = datetime.now(timezone.utc)
    earliest_expiry = str(snapshots[2]) if snapshots and snapshots[2] else None
    stale = True
    if earliest_expiry:
        try:
            stale = datetime.fromisoformat(earliest_expiry.replace("Z", "+00:00")) <= now
        except ValueError:
            stale = True
    return {
        "tenant_id": tenant, "source": source_id,
        "status": (
            "unconfigured" if run is None else
            "degraded" if str(run[1]) not in {"observed", "empty"} else
            "stale" if not snapshots or int(snapshots[0] or 0) == 0 or stale else "healthy"
        ),
        "last_run": (None if run is None else {
            "run_id": str(run[0]), "status": str(run[1]), "records_seen": int(run[2] or 0),
            "records_inserted": int(run[3] or 0), "records_replayed": int(run[4] or 0),
            "finished_at": run[5], "error": run[6],
        }),
        "projection": {
            "snapshot_count": int(snapshots[0] or 0) if snapshots else 0,
            "latest_observed_at": snapshots[1] if snapshots else None,
            "earliest_expires_at": earliest_expiry,
        },
    }
