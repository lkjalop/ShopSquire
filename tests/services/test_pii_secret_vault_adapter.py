import hashlib
import json

import pytest

from src.app.adapters.pii_secret_vault import (
    JsonSecretDestinationVault,
    destination_vault_from_env,
)


def _record(*, tenant: str = "tenant-a", token: str = "dst-token-1") -> str:
    return json.dumps({
        "schema_version": "shopsquire.destination.v1",
        "tenant_id": tenant,
        "destination_token_digest": hashlib.sha256(token.encode()).hexdigest(),
        "allowed_purposes": ["deliver_order"],
        "fields": {
            "recipient_name": "Synthetic Buyer",
            "address_line_1": "1 Example Street",
            "postal_code": "2000",
            "phone": "0000000000",
        },
    })


def test_secret_vault_resolves_only_requested_fields_with_hashed_locator():
    seen = []

    def read(locator: str) -> str:
        seen.append(locator)
        return _record()

    vault = JsonSecretDestinationVault(read_secret=read, namespace="shopsquire-destination")
    result = vault.resolve(
        tenant_id="tenant-a", destination_token="dst-token-1",
        fields=frozenset({"recipient_name", "postal_code"}), purpose="deliver_order",
    )

    assert result == {"recipient_name": "Synthetic Buyer", "postal_code": "2000"}
    assert "dst-token-1" not in seen[0]
    assert "tenant-a" not in seen[0]


def test_secret_vault_rejects_cross_tenant_or_wrong_purpose():
    vault = JsonSecretDestinationVault(read_secret=lambda _locator: _record())
    with pytest.raises(PermissionError, match="destination_record_tenant_mismatch"):
        vault.resolve(
            tenant_id="tenant-b", destination_token="dst-token-1",
            fields=frozenset({"postal_code"}), purpose="deliver_order",
        )
    with pytest.raises(PermissionError, match="destination_record_purpose_not_allowed"):
        vault.resolve(
            tenant_id="tenant-a", destination_token="dst-token-1",
            fields=frozenset({"postal_code"}), purpose="marketing",
        )

def test_secret_vault_rejects_tampered_token_and_unavailable_fields():
    vault = JsonSecretDestinationVault(read_secret=lambda _locator: _record())
    with pytest.raises(PermissionError, match="destination_record_token_mismatch"):
        vault.resolve(
            tenant_id="tenant-a", destination_token="different-token",
            fields=frozenset({"postal_code"}), purpose="deliver_order",
        )
    with pytest.raises(LookupError, match="destination_record_fields_unavailable"):
        vault.resolve(
            tenant_id="tenant-a", destination_token="dst-token-1",
            fields=frozenset({"date_of_birth"}), purpose="deliver_order",
        )


def test_runtime_factory_fails_closed_without_a_provider(monkeypatch):
    monkeypatch.delenv("DESTINATION_PII_VAULT_PROVIDER", raising=False)
    with pytest.raises(RuntimeError, match="destination_pii_vault_provider_required"):
        destination_vault_from_env()


def test_runtime_factory_composes_azure_managed_identity_adapter(monkeypatch):
    marker = object()
    monkeypatch.setenv("DESTINATION_PII_VAULT_PROVIDER", "azure_key_vault")
    monkeypatch.setenv("DESTINATION_PII_AZURE_VAULT_URL", "https://vault.example.test")
    monkeypatch.setenv("DESTINATION_PII_SECRET_NAMESPACE", "tenant-destination")
    monkeypatch.setattr(
        JsonSecretDestinationVault,
        "from_azure_key_vault",
        classmethod(lambda cls, **kwargs: (marker, kwargs)),
    )

    vault, args = destination_vault_from_env()

    assert vault is marker
    assert args == {
        "vault_url": "https://vault.example.test",
        "namespace": "tenant-destination",
    }
