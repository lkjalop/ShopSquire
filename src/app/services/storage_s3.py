import os
from typing import Optional


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
                import boto3
                endpoint_url = os.getenv("S3_ENDPOINT_URL") or os.getenv("MINIO_ENDPOINT")
                self.s3 = boto3.client(
                    "s3",
                    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
                    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
                    region_name=os.getenv("AWS_REGION"),
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


def get_default_storage() -> S3Storage:
    return S3Storage()
