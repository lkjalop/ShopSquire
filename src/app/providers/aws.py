from __future__ import annotations

from typing import Any


def get_client(service: str, **kwargs: Any) -> Any:
    import boto3  # type: ignore

    return boto3.client(service, **kwargs)


def get_secret_value(secret_id: str, region: str) -> dict[str, Any]:
    client = get_client("secretsmanager", region_name=region)
    return client.get_secret_value(SecretId=secret_id)


def get_s3_client(
    *,
    access_key_id: str | None,
    secret_access_key: str | None,
    region: str | None,
    endpoint_url: str | None,
) -> Any:
    return get_client(
        "s3",
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region,
        endpoint_url=endpoint_url,
    )
