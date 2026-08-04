import os
from typing import Optional, Protocol


class ObjectStorage(Protocol):
    """Provider-neutral object-storage contract used by application routers."""

    def upload_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> dict: ...

    def presign_url(self, key: str, expires_in: int = 3600) -> dict: ...

    def presign_put_url(
        self,
        key: str,
        expires_in: int = 3600,
        content_type: Optional[str] = None,
    ) -> dict: ...

    def health(self) -> dict: ...


class S3Storage:
    """Simple S3-compatible storage adapter scaffold.

    Uses `boto3` if available and `AWS_S3_BUCKET` env var configured.
    Otherwise provides no-op/stub behavior for local dev.
    """

    def __init__(self, bucket: Optional[str] = None):
        self.bucket = bucket or os.getenv("AWS_S3_BUCKET")
        self.enabled = False
        self.s3 = None
        if self.bucket:
            try:
                from src.app.providers.aws import get_s3_client

                endpoint_url = os.getenv("S3_ENDPOINT_URL") or os.getenv("MINIO_ENDPOINT")
                self.s3 = get_s3_client(
                    access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                    secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    region=os.getenv("AWS_REGION"),
                    endpoint_url=endpoint_url,
                )
                self.enabled = True
            except Exception:
                self.s3 = None
                self.enabled = False

    def upload_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> dict:
        if not self.enabled or not self.s3:
            # local dev: write to ./static/uploads
            try:
                import pathlib

                p = pathlib.Path("static/uploads")
                p.mkdir(parents=True, exist_ok=True)
                fp = p.joinpath(key)
                fp.write_bytes(data)
                return {"ok": True, "url": f"/static/uploads/{key}"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        try:
            extra = {}
            if content_type:
                extra["ContentType"] = content_type
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
            url = f"https://{self.bucket}.s3.amazonaws.com/{key}"
            return {"ok": True, "url": url}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def presign_url(self, key: str, expires_in: int = 3600) -> dict:
        if not self.enabled or not self.s3:
            # local dev fallback
            return {"ok": True, "url": f"/static/uploads/{key}"}
        try:
            url = self.s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in)
            return {"ok": True, "url": url}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def presign_put_url(self, key: str, expires_in: int = 3600, content_type: Optional[str] = None) -> dict:
        if not self.enabled or not self.s3:
            return {"ok": True, "url": f"/static/uploads/{key}", "method": "PUT", "fields": {}}
        try:
            params = {"Bucket": self.bucket, "Key": key}
            if content_type:
                params["ContentType"] = content_type
            url = self.s3.generate_presigned_url("put_object", Params=params, ExpiresIn=expires_in)
            return {"ok": True, "url": url, "method": "PUT"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def health(self) -> dict:
        if not self.enabled or not self.s3:
            return {"ok": False, "reason": "disabled"}
        try:
            # Best-effort: list buckets to validate connectivity
            self.s3.list_buckets()
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


class AzureBlobStorage:
    """Azure Blob adapter using workload identity instead of embedded credentials."""

    def __init__(
        self,
        *,
        account_url: Optional[str] = None,
        container: Optional[str] = None,
    ):
        self.account_url = account_url or os.getenv("AZURE_STORAGE_ACCOUNT_URL")
        self.container = container or os.getenv("AZURE_STORAGE_CONTAINER")
        self.container_client = self._build_container_client()
        self.enabled = self.container_client is not None

    def _build_container_client(self):
        if not self.account_url or not self.container:
            return None
        try:
            from src.app.providers.azure import get_blob_container
        except Exception:
            return None
        try:
            return get_blob_container(self.account_url, self.container)
        except Exception:
            return None

    def upload_bytes(self, key: str, data: bytes, content_type: Optional[str] = None) -> dict:
        if not self.enabled or self.container_client is None:
            return {"ok": False, "error": "azure_blob_not_configured"}
        try:
            kwargs = {"overwrite": False}
            if content_type:
                from src.app.providers.azure import blob_content_settings

                kwargs["content_settings"] = blob_content_settings(content_type)
            blob = self.container_client.get_blob_client(key)
            blob.upload_blob(data, **kwargs)
            return {"ok": True, "url": blob.url}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def presign_url(self, key: str, expires_in: int = 3600) -> dict:
        del expires_in
        # Workload identity deliberately does not mint bearer URLs. Private
        # downloads should be proxied through an authorized application route.
        return {"ok": False, "error": "azure_user_delegation_url_not_configured", "key": key}

    def presign_put_url(
        self,
        key: str,
        expires_in: int = 3600,
        content_type: Optional[str] = None,
    ) -> dict:
        del expires_in, content_type
        return {"ok": False, "error": "azure_user_delegation_url_not_configured", "key": key}

    def health(self) -> dict:
        if not self.enabled or self.container_client is None:
            return {"ok": False, "reason": "disabled"}
        try:
            self.container_client.get_container_properties()
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}


def get_default_storage() -> ObjectStorage:
    provider = str(os.getenv("OBJECT_STORAGE_PROVIDER", "s3") or "s3").strip().lower()
    if provider in {"s3", "aws", "minio", "local"}:
        return S3Storage()
    if provider in {"azure", "azure-blob"}:
        return AzureBlobStorage()
    raise RuntimeError(f"unsupported_object_storage_provider:{provider}")
