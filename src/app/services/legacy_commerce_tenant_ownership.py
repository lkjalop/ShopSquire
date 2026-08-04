"""Fail-closed tenant ownership operations for legacy commerce subjects."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text


TABLE_SUBJECT_PREDICATES = {
    "order_sessions": "uid=:uid",
    "orders": "customer_id=:uid",
    "customers": "id=:uid",
}


def erase_authoritatively_owned_subject_rows(
    db,
    *,
    tenant_id: str,
    uid: str,
) -> dict[str, Any]:
    """Erase only active-tenant rows and report evidence-free rows.

    Rows belonging to another tenant are neither counted nor modified. Rows
    without classified ownership are reported for operator remediation.
    """
    tenant = str(tenant_id or "").strip()
    subject = str(uid or "").strip()
    if not tenant or not subject:
        raise ValueError("tenant_and_subject_required")

    unclassified: dict[str, int] = {}
    deleted: dict[str, int] = {}
    for table, predicate in TABLE_SUBJECT_PREDICATES.items():
        count = db.execute(
            text(
                f"SELECT COUNT(*) FROM {table} WHERE {predicate} "
                "AND (tenant_id IS NULL OR tenant_ownership_status='unclassified')"
            ),
            {"uid": subject},
        ).scalar()
        unclassified[table] = int(count or 0)

    # Delete dependent sessions before their orders.
    for table in ("order_sessions", "orders", "customers"):
        predicate = TABLE_SUBJECT_PREDICATES[table]
        result = db.execute(
            text(
                f"DELETE FROM {table} WHERE {predicate} "
                "AND tenant_id=:tenant_id "
                "AND tenant_ownership_status!='unclassified'"
            ),
            {"uid": subject, "tenant_id": tenant},
        )
        deleted[table] = int(getattr(result, "rowcount", 0) or 0)

    return {"deleted": deleted, "unclassified": unclassified}
