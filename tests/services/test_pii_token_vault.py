import pytest

from src.app.services.pii_token_vault import resolve_authorized_destination


class _Vault:
    calls = []

    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "recipient_name": "Ada", "street_address": "1 Main St",
            "postal_code": "2000", "email": "must-not-leak@example.test",
        }


def _grant(status="authorized"):
    return {
        "authorization_id": "AUTH-1", "status": status, "case_id": "CASE-1",
        "supplier_id": "SUP-1", "destination_token": "DEST-1",
        "purpose": "deliver_order",
        "permitted_fields": ["recipient_name", "street_address", "postal_code"],
    }


def test_vault_releases_only_minimum_authorized_fields_and_audits_no_values():
    vault = _Vault()
    events = []
    released = resolve_authorized_destination(
        tenant_id="t1", case_id="CASE-1", supplier_id="SUP-1",
        authorization=_grant(), vault=vault, audit=events.append,
    )
    assert released == {
        "postal_code": "2000", "recipient_name": "Ada", "street_address": "1 Main St",
    }
    assert vault.calls[-1]["fields"] == frozenset(released)
    assert events == [{
        "event": "direct_ship_pii_released", "tenant_id": "t1", "case_id": "CASE-1",
        "supplier_id": "SUP-1", "authorization_id": "AUTH-1",
        "destination_token": "DEST-1", "fields": sorted(released),
        "purpose": "deliver_order", "values_recorded": False,
    }]


@pytest.mark.parametrize("status", ["withdrawn", "expired", "pending", None])
def test_inactive_authorization_never_calls_vault(status):
    vault = _Vault()
    vault.calls = []
    with pytest.raises(PermissionError, match="authorization_inactive"):
        resolve_authorized_destination(
            tenant_id="t1", case_id="CASE-1", supplier_id="SUP-1",
            authorization=_grant(status), vault=vault, audit=lambda event: None,
        )
    assert vault.calls == []
