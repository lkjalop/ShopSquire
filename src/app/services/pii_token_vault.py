"""Provider-neutral destination-token resolution for governed direct shipping.

ShopSquire stores only an opaque destination token in procurement records.  A deployment supplies
an implementation backed by its approved privacy vault (for example Azure Key Vault plus an
encrypted record store).  Resolution is purpose-bound and returns only fields authorized by the
buyer; callers cannot request arbitrary PII.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol


class DestinationTokenVault(Protocol):
    def resolve(
        self, *, tenant_id: str, destination_token: str, fields: frozenset[str], purpose: str,
    ) -> Mapping[str, Any]: ...


def resolve_authorized_destination(
    *, tenant_id: str, case_id: str, supplier_id: str,
    authorization: Mapping[str, Any] | None, vault: DestinationTokenVault,
    audit: Callable[[dict[str, Any]], None], purpose: str = "deliver_order",
) -> dict[str, Any]:
    """Resolve the minimum authorized fields without persisting or returning extras."""
    grant = dict(authorization or {})
    if grant.get("status") != "authorized":
        raise PermissionError("direct_ship_authorization_inactive")
    if str(grant.get("case_id")) != str(case_id):
        raise PermissionError("direct_ship_case_scope_mismatch")
    if str(grant.get("supplier_id")) != str(supplier_id):
        raise PermissionError("direct_ship_supplier_scope_mismatch")
    if str(grant.get("purpose")) != str(purpose):
        raise PermissionError("direct_ship_purpose_scope_mismatch")
    token = str(grant.get("destination_token") or "").strip()
    fields = frozenset(str(item) for item in grant.get("permitted_fields") or [] if str(item))
    if not token or not fields:
        raise PermissionError("direct_ship_scope_incomplete")
    resolved = dict(vault.resolve(
        tenant_id=str(tenant_id), destination_token=token, fields=fields, purpose=str(purpose),
    ))
    missing = sorted(field for field in fields if field not in resolved)
    if missing:
        raise LookupError("destination_token_fields_unavailable:" + ",".join(missing))
    released = {field: resolved[field] for field in sorted(fields)}
    audit({
        "event": "direct_ship_pii_released", "tenant_id": str(tenant_id),
        "case_id": str(case_id), "supplier_id": str(supplier_id),
        "authorization_id": str(grant.get("authorization_id") or ""),
        "destination_token": token, "fields": sorted(fields), "purpose": str(purpose),
        "values_recorded": False,
    })
    return released
