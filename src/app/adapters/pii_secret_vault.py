"""Cloud-adapter implementation of the destination-token vault protocol.

The canonical PII contract lives in ``services.pii_token_vault``. This edge adapter stores one
versioned JSON envelope per opaque destination token using an injected secret reader. Azure Key
Vault and AWS Secrets Manager construction is isolated here and in ``src.app.providers``.
"""
from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from typing import Any, Mapping


SecretReader = Callable[[str], str | None]


class JsonSecretDestinationVault:
    def __init__(
        self,
        *,
        read_secret: SecretReader,
        namespace: str = "shopsquire-destination",
    ) -> None:
        self._read_secret = read_secret
        self._namespace = str(namespace or "shopsquire-destination").strip("- ")

    @classmethod
    def from_azure_key_vault(
        cls,
        *,
        vault_url: str,
        namespace: str = "shopsquire-destination",
    ) -> "JsonSecretDestinationVault":
        from src.app.providers.azure import get_key_vault_secret

        return cls(
            read_secret=lambda locator: get_key_vault_secret(vault_url, locator),
            namespace=namespace,
        )

    @classmethod
    def from_aws_secrets_manager(
        cls,
        *,
        region: str,
        namespace: str = "shopsquire-destination",
    ) -> "JsonSecretDestinationVault":
        from src.app.providers.aws import get_secret_value

        def read(locator: str) -> str | None:
            response = get_secret_value(locator, region)
            secret = response.get("SecretString")
            if secret is not None:
                return str(secret)
            binary = response.get("SecretBinary")
            if binary is None:
                return None
            raw = binary if isinstance(binary, bytes) else base64.b64decode(binary)
            return raw.decode("utf-8")

        return cls(read_secret=read, namespace=namespace)

    def _locator(self, *, tenant_id: str, destination_token: str) -> str:
        tenant_digest = hashlib.sha256(str(tenant_id).encode()).hexdigest()[:12]
        token_digest = hashlib.sha256(str(destination_token).encode()).hexdigest()
        return f"{self._namespace}-{tenant_digest}-{token_digest[:32]}"

    def resolve(
        self,
        *,
        tenant_id: str,
        destination_token: str,
        fields: frozenset[str],
        purpose: str,
    ) -> Mapping[str, Any]:
        tenant = str(tenant_id or "").strip()
        token = str(destination_token or "").strip()
        requested = frozenset(str(field).strip() for field in fields if str(field).strip())
        use = str(purpose or "").strip()
        if not tenant or not token or not requested or not use:
            raise ValueError("destination_record_scope_required")
        locator = self._locator(tenant_id=tenant, destination_token=token)
        raw = self._read_secret(locator)
        if not raw:
            raise LookupError("destination_record_unavailable")
        try:
            record = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("destination_record_malformed") from exc
        if not isinstance(record, dict):
            raise ValueError("destination_record_malformed")
        if record.get("schema_version") != "shopsquire.destination.v1":
            raise ValueError("destination_record_schema_unsupported")
        if str(record.get("tenant_id") or "") != tenant:
            raise PermissionError("destination_record_tenant_mismatch")
        expected_digest = hashlib.sha256(token.encode()).hexdigest()
        if str(record.get("destination_token_digest") or "") != expected_digest:
            raise PermissionError("destination_record_token_mismatch")
        purposes = frozenset(str(item) for item in record.get("allowed_purposes") or [])
        if use not in purposes:
            raise PermissionError("destination_record_purpose_not_allowed")
        available = record.get("fields")
        if not isinstance(available, dict):
            raise ValueError("destination_record_fields_malformed")
        missing = sorted(requested - set(available))
        if missing:
            raise LookupError("destination_record_fields_unavailable:" + ",".join(missing))
        return {field: available[field] for field in sorted(requested)}
