"""Bind communications to Party only from authoritative tenant-scoped identities."""
from __future__ import annotations

from typing import Any

from src.app.services.account_intelligence import (
    resolve_authoritative_external_identity_in_session,
)


AUTHORITIES = frozenset({
    "authenticated_buyer_principal",
    "approved_supplier_registry",
    "verified_connector_sender",
})


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
