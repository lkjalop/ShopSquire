"""Grounded recovery options for unresolved supplier schedules.

The core does not infer product compatibility or supplier inventory.  It only
projects tenant-owned mappings that are still fresh and joins them to approved
supplier identities.  Every option remains advisory until a governed supplier
confirmation is received.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import inspect, text


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _freshness(observed_at: str, *, now: datetime, max_age: timedelta) -> str:
    return "current" if _utc(observed_at) >= now - max_age else "stale"


def project_supply_recovery(
    db,
    *,
    tenant_id: str,
    sku: str,
    excluded_supplier_id: str | None = None,
    now: datetime | None = None,
    max_mapping_age: timedelta = timedelta(days=30),
    limit: int = 5,
) -> dict[str, Any]:
    """Return approved supplier and qualified-substitute recovery candidates.

    Carrying a SKU is not evidence of present inventory.  Consequently every
    candidate has ``availability=unknown`` and ``action=request_confirmation``.
    """
    tenant = str(tenant_id or "").strip()
    item = str(sku or "").strip()
    if not tenant or not item:
        raise ValueError("supply_recovery_scope_required")
    # Inspect through the session connection.  Opening a second inspector connection
    # can roll back an active SQLite fixture transaction on SingletonThreadPool.
    tables = set(inspect(db.connection()).get_table_names())
    required = {"tenant_supply_mapping", "suppliers", "supplier_products",
                "trusted_supplier_domains"}
    if not required.issubset(tables):
        return {
            "status": "degraded",
            "reason": "tenant_supply_mappings_unavailable",
            "alternative_suppliers": [],
            "qualified_substitutes": [],
            "external_action": "none",
        }
    clock = now or datetime.now(timezone.utc)
    mappings = db.execute(text(
        "SELECT mapping_type,external_id,canonical_id,source,source_version,"
        "observed_at,evidence_ref,confidence FROM tenant_supply_mapping "
        "WHERE tenant_id=:tenant AND status='active' "
        "AND mapping_type='supplier' "
        "ORDER BY observed_at DESC,id DESC"
    ), {"tenant": tenant, "sku": item}).fetchall()
    supplier_authority: dict[str, dict[str, Any]] = {}
    substitute_authority: dict[str, dict[str, Any]] = {}
    for row in mappings:
        authority = {
            "source": str(row[3]), "source_version": str(row[4]),
            "observed_at": str(row[5]), "evidence_ref": str(row[6]),
            "confidence": float(row[7]),
            "freshness": _freshness(str(row[5]), now=clock, max_age=max_mapping_age),
        }
        if authority["freshness"] != "current":
            continue
        supplier_authority.setdefault(str(row[2]), authority)

    if "tenant_supply_relationship" in tables:
        relationship_rows = db.execute(text(
            "SELECT object_id,source,source_version,observed_at,evidence_ref,confidence "
            "FROM tenant_supply_relationship WHERE tenant_id=:tenant AND status='active' "
            "AND relationship_type='qualified_substitute_for' AND subject_id=:sku "
            "ORDER BY observed_at DESC,id DESC"
        ), {"tenant": tenant, "sku": item}).fetchall()
        for row in relationship_rows:
            authority = {
                "source": str(row[1]), "source_version": str(row[2]),
                "observed_at": str(row[3]), "evidence_ref": str(row[4]),
                "confidence": float(row[5]),
                "freshness": _freshness(str(row[3]), now=clock, max_age=max_mapping_age),
            }
            if authority["freshness"] == "current":
                substitute_authority.setdefault(str(row[0]), authority)

    supplier_rows = db.execute(text(
        "SELECT s.id,s.name,s.reliability_score,sp.sku,d.domain "
        "FROM suppliers s JOIN supplier_products sp ON sp.supplier_id=s.id "
        "JOIN trusted_supplier_domains d ON d.supplier_id=s.id AND d.active=1 "
        "WHERE s.active=1 AND sp.sku=:sku "
        "ORDER BY s.reliability_score DESC,s.id"
    ), {"sku": item}).fetchall()
    alternatives = []
    seen: set[str] = set()
    for row in supplier_rows:
        supplier_id = str(row[0])
        if supplier_id == str(excluded_supplier_id or "") or supplier_id in seen:
            continue
        authority = supplier_authority.get(supplier_id)
        if authority is None:
            continue
        seen.add(supplier_id)
        alternatives.append({
            "supplier_id": supplier_id,
            "supplier_name": str(row[1] or supplier_id),
            "approved_domain": str(row[4]),
            "reliability_score": float(row[2] or 0.0),
            "availability": "unknown",
            "action": "request_confirmation",
            "authority": authority,
        })
        if len(alternatives) >= max(1, int(limit)):
            break

    substitutes = []
    for substitute_sku, authority in list(substitute_authority.items())[:max(1, int(limit))]:
        carrier = db.execute(text(
            "SELECT s.id,s.name,d.domain FROM suppliers s "
            "JOIN supplier_products sp ON sp.supplier_id=s.id "
            "JOIN trusted_supplier_domains d ON d.supplier_id=s.id AND d.active=1 "
            "WHERE s.active=1 AND sp.sku=:sku ORDER BY s.reliability_score DESC,s.id LIMIT 1"
        ), {"sku": substitute_sku}).fetchone()
        if carrier is None:
            continue
        substitutes.append({
            "sku": substitute_sku,
            "supplier_id": str(carrier[0]),
            "supplier_name": str(carrier[1] or carrier[0]),
            "approved_domain": str(carrier[2]),
            "qualification": "tenant_approved_mapping",
            "availability": "unknown",
            "action": "request_confirmation",
            "authority": authority,
        })
    return {
        "status": "options_available" if alternatives or substitutes else "insufficient_evidence",
        "reason": None if alternatives or substitutes else "no_fresh_approved_recovery_mapping",
        "alternative_suppliers": alternatives,
        "qualified_substitutes": substitutes,
        "state_prevented": "unconfirmed_supply_presented_as_available",
        "external_action": "none",
    }
