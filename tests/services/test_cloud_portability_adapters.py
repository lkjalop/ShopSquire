from __future__ import annotations

import pytest

from src.app.services import secrets_manager
from src.app.services.storage_s3 import AzureBlobStorage, S3Storage, get_default_storage


def test_azure_key_vault_reference_is_resolved_and_cached(monkeypatch) -> None:
    secrets_manager._CACHE.clear()
    calls = []

    def fake_get(vault_name, secret_name, version=None):
        calls.append((vault_name, secret_name, version))
        return "managed-secret"

    monkeypatch.setattr(secrets_manager, "_azure_kv_get", fake_get)
    ref = "azure-kv://shopsquire-prod/signing-key#version-2"
    assert secrets_manager.resolve_secret(ref) == "managed-secret"
    assert secrets_manager.resolve_secret(ref) == "managed-secret"
    assert calls == [("shopsquire-prod", "signing-key", "version-2")]


def test_storage_provider_selection_is_explicit(monkeypatch) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "s3")
    assert isinstance(get_default_storage(), S3Storage)

    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "azure")
    monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_URL", "https://example.blob.core.windows.net")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER", "evidence")
    monkeypatch.setattr(AzureBlobStorage, "_build_container_client", lambda self: object())
    assert isinstance(get_default_storage(), AzureBlobStorage)

    monkeypatch.setenv("OBJECT_STORAGE_PROVIDER", "unknown")
    with pytest.raises(RuntimeError, match="unsupported_object_storage_provider"):
        get_default_storage()
