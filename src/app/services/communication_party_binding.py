"""Bind communications to Party only from authoritative tenant-scoped identities."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from src.app.services.account_intelligence import (
    resolve_authoritative_external_identity_in_session,
)


AUTHORITIES = frozenset({
    "authenticated_buyer_principal",
    "approved_supplier_registry",
    "verified_connector_sender",
})


def require_authoritative_party_ref(
    db,
    *,
    tenant_id: str,
    party_ref: str,
) -> dict[str, str]:
    """Resolve only a tenant-owned Party backed by a verified identity record."""
    tenant = str(tenant_id or "").strip()
    party = str(party_ref or "").strip()
    if not tenant or not party:
        raise ValueError("authoritative_party_binding_required")
    row = db.execute(
        text(
            """
            SELECT p.party_type, pei.authority, pei.provenance_ref
            FROM party p
            JOIN party_external_identity pei
              ON pei.tenant_id=p.tenant_id AND pei.party_id=p.id
            WHERE p.tenant_id=:tenant AND p.id=:party
              AND p.status='active'
              AND pei.authority!='legacy_unverified'
              AND pei.verified_at IS NOT NULL
            ORDER BY pei.verified_at DESC
            LIMIT 1
            """
        ),
        {"tenant": tenant, "party": party},
    ).fetchone()
    if not row:
        raise ValueError("authoritative_party_binding_required")
    return {
        "party_id": party,
        "party_type": str(row[0]),
        "authority": str(row[1]),
        "provenance_ref": str(row[2] or ""),
    }


def bind_authoritative_party(
    db,
    *,
    tenant_id: str,
    party_type: str,
    source: str,
    object_type: str,
    external_id: str,
    authority: str,
    provenance_ref: str,
    display_name: str | None = None,
) -> dict[str, Any]:
    tenant = str(tenant_id or "").strip()
    auth = str(authority or "").strip().lower()
    provenance = str(provenance_ref or "").strip()
    if not tenant or auth not in AUTHORITIES or not provenance:
        raise ValueError("authoritative_party_binding_required")
    return resolve_authoritative_external_identity_in_session(
        db,
        tenant_id=tenant,
        source=source,
        object_type=object_type,
        external_id=external_id,
        party_type=party_type,
        display_name=display_name,
        authority=auth,
        provenance_ref=provenance,
    )
