from __future__ import annotations

from typing import Any


def get_key_vault_secret(
    vault_url: str,
    secret_name: str,
    version: str | None = None,
) -> str | None:
    from azure.identity import DefaultAzureCredential  # type: ignore
    from azure.keyvault.secrets import SecretClient  # type: ignore

    client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
    return client.get_secret(secret_name, version=version).value


def get_blob_container(account_url: str, container: str) -> Any:
    from azure.identity import DefaultAzureCredential  # type: ignore
    from azure.storage.blob import BlobServiceClient  # type: ignore

    service = BlobServiceClient(
        account_url=account_url,
        credential=DefaultAzureCredential(),
    )
    return service.get_container_client(container)


def blob_content_settings(content_type: str) -> Any:
    from azure.storage.blob import ContentSettings  # type: ignore

    return ContentSettings(content_type=content_type)


def get_cognitive_token() -> str:
    from azure.identity import DefaultAzureCredential  # type: ignore

    token = DefaultAzureCredential().get_token(
        "https://cognitiveservices.azure.com/.default"
    )
    return str(token.token)
