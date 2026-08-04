"""Append-only tenant identity mappings for products, suppliers, and facilities."""
from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text


MAPPING_TYPES = frozenset({"product", "supplier", "facility"})


def _time(value: str) -> str:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def register_supply_mapping(
    db, *, tenant_id: str, mapping_type: str, external_id: str, canonical_id: str,
    source: str, source_version: str, observed_at: str, evidence_ref: str,
    confidence: float,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    kind = str(mapping_type or "").strip().lower()
    external = str(external_id or "").strip()
    canonical = str(canonical_id or "").strip()
    source_id = str(source or "").strip().lower()
    version = str(source_version or "").strip()
    evidence = str(evidence_ref or "").strip()
    if not tenant or kind not in MAPPING_TYPES or not all((external, canonical, source_id, version, evidence)):
        raise ValueError("invalid_supply_mapping")
    score = float(confidence)
    if not 0.0 <= score <= 1.0:
        raise ValueError("invalid_supply_mapping_confidence")
    observed = _time(observed_at)
    identity = "|".join((tenant, kind, external, source_id, version))
    mapping_id = hashlib.sha256(identity.encode()).hexdigest()
    existing = db.execute(text(
        "SELECT canonical_id,status FROM tenant_supply_mapping WHERE id=:id"
    ), {"id": mapping_id}).fetchone()
    if existing:
        if str(existing[0]) != canonical:
            raise ValueError("mapping_version_conflict")
        return {"mapping_id": mapping_id, "canonical_id": canonical,
                "status": str(existing[1]), "idempotent": True}
    db.execute(text(
        "UPDATE tenant_supply_mapping SET status='superseded' WHERE tenant_id=:t "
        "AND mapping_type=:kind AND external_id=:external AND source=:source AND status='active'"
    ), {"t": tenant, "kind": kind, "external": external, "source": source_id})
    db.execute(text(
        "INSERT INTO tenant_supply_mapping "
        "(id,tenant_id,mapping_type,external_id,canonical_id,source,source_version,observed_at,"
        "evidence_ref,confidence,status) VALUES "
        "(:id,:t,:kind,:external,:canonical,:source,:version,:observed,:evidence,:confidence,'active')"
    ), {"id": mapping_id, "t": tenant, "kind": kind, "external": external,
        "canonical": canonical, "source": source_id, "version": version,
        "observed": observed, "evidence": evidence, "confidence": score})
    return {"mapping_id": mapping_id, "canonical_id": canonical,
            "status": "active", "idempotent": False}


def resolve_supply_mapping(
    db, *, tenant_id: str, mapping_type: str, external_id: str,
) -> dict[str, Any] | None:
    row = db.execute(text(
        "SELECT canonical_id,source,source_version,observed_at,evidence_ref,confidence "
        "FROM tenant_supply_mapping WHERE tenant_id=:t AND mapping_type=:kind "
        "AND external_id=:external AND status='active' ORDER BY observed_at DESC,id DESC LIMIT 1"
    ), {"t": tenant_id, "kind": mapping_type, "external": external_id}).fetchone()
    if row is None:
        return None
    return {"canonical_id": str(row[0]), "source": str(row[1]),
            "source_version": str(row[2]), "observed_at": str(row[3]),
            "evidence_ref": str(row[4]), "confidence": float(row[5])}


def register_supply_relationship(
    db, *, tenant_id: str, relationship_type: str, subject_id: str, object_id: str,
    source: str, source_version: str, observed_at: str, evidence_ref: str, confidence: float,
) -> dict[str, Any]:
    """Register a tenant-approved relationship without overloading identity mappings."""
    tenant = str(tenant_id or "").strip()
    relation = str(relationship_type or "").strip().lower()
    subject = str(subject_id or "").strip()
    object_ref = str(object_id or "").strip()
    if relation not in {"qualified_substitute_for", "transported_via", "composed_of"}:
        raise ValueError("invalid_supply_relationship")
    if not all((tenant, subject, object_ref, source, source_version, evidence_ref)):
        raise ValueError("invalid_supply_relationship")
    score = float(confidence)
    if not 0.0 <= score <= 1.0:
        raise ValueError("invalid_supply_relationship_confidence")
    observed = _time(observed_at)
    identity = "|".join((tenant, relation, subject, object_ref, source, source_version))
    relationship_id = hashlib.sha256(identity.encode()).hexdigest()
    existing = db.execute(text(
        "SELECT status FROM tenant_supply_relationship WHERE id=:id"
    ), {"id": relationship_id}).fetchone()
    if existing:
        return {"relationship_id": relationship_id, "status": str(existing[0]), "idempotent": True}
    db.execute(text(
        "UPDATE tenant_supply_relationship SET status='superseded' WHERE tenant_id=:t "
        "AND relationship_type=:kind AND subject_id=:subject AND object_id=:object "
        "AND source=:source AND status='active'"
    ), {"t": tenant, "kind": relation, "subject": subject, "object": object_ref, "source": source})
    db.execute(text(
        "INSERT INTO tenant_supply_relationship "
        "(id,tenant_id,relationship_type,subject_id,object_id,source,source_version,observed_at,"
        "evidence_ref,confidence,status) VALUES "
        "(:id,:t,:kind,:subject,:object,:source,:version,:observed,:evidence,:confidence,'active')"
    ), {"id": relationship_id, "t": tenant, "kind": relation, "subject": subject,
        "object": object_ref, "source": source, "version": source_version,
        "observed": observed, "evidence": evidence_ref, "confidence": score})
    return {"relationship_id": relationship_id, "status": "active", "idempotent": False}


def import_supply_mapping_csv(
    db, path: str | Path, *, tenant_id: str, source: str,
) -> dict[str, Any]:
    results = []
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            try:
                results.append(register_supply_mapping(
                    db, tenant_id=tenant_id, mapping_type=str(row.get("mapping_type") or ""),
                    external_id=str(row.get("external_id") or ""),
                    canonical_id=str(row.get("canonical_id") or ""), source=source,
                    source_version=str(row.get("source_version") or ""),
                    observed_at=str(row.get("observed_at") or ""),
                    evidence_ref=str(row.get("evidence_ref") or ""),
                    confidence=float(row.get("confidence") or 0.0),
                ))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"invalid_supply_mapping_at_line_{line_number}:{exc}") from exc
    return {"tenant_id": tenant_id, "source": source, "records": results,
            "inserted": sum(not row["idempotent"] for row in results),
            "replayed": sum(row["idempotent"] for row in results)}


def supply_mapping_health(
    db,
    *,
    tenant_id: str,
    evaluated_at: str | None = None,
    freshness_sla_hours: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Report coverage and age without treating an old mapping as healthy.

    SLAs are deployment policy, not facts embedded in the mapping rows. Callers
    may supply a per-type policy; absent policy preserves the legacy coverage-
    only result while still exposing age metadata when an evaluation time is
    provided.
    """
    rows = db.execute(text(
        "SELECT mapping_type,COUNT(*),MAX(observed_at),COUNT(DISTINCT source) "
        "FROM tenant_supply_mapping WHERE tenant_id=:t AND status='active' GROUP BY mapping_type"
    ), {"t": tenant_id}).fetchall()
    evaluated = _utc_time(evaluated_at) if evaluated_at else datetime.now(timezone.utc)
    slas = {str(key): float(value) for key, value in (freshness_sla_hours or {}).items()}
    by_type: dict[str, dict[str, Any]] = {}
    stale: list[str] = []
    for row in rows:
        kind = str(row[0])
        observed = _utc_time(str(row[2]))
        age_hours = max(0.0, (evaluated - observed).total_seconds() / 3600)
        sla = slas.get(kind)
        freshness_status = "not_evaluated"
        if sla is not None:
            freshness_status = "fresh" if age_hours <= sla else "stale"
            if freshness_status == "stale":
                stale.append(kind)
        by_type[kind] = {
            "active": int(row[1]),
            "latest_observed_at": row[2],
            "source_count": int(row[3]),
            "age_hours": round(age_hours, 3),
            "freshness_sla_hours": sla,
            "freshness_status": freshness_status,
        }
    missing = sorted(MAPPING_TYPES - set(by_type))
    status = "incomplete" if missing else ("degraded" if stale else "ready")
    return {
        "tenant_id": tenant_id,
        "status": status,
        "evaluated_at": evaluated.isoformat(),
        "by_type": by_type,
        "missing_mapping_types": missing,
        "stale_mapping_types": sorted(stale),
    }


def _utc_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
