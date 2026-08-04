"""Append-only WORM audit log with optional S3 Object Lock and daily HMAC anchor.

Configuration (all optional — local-file mode works without any env vars):
    WORM_S3_BUCKET             — S3 bucket with Object Lock enabled; enables S3 upload
    WORM_S3_KEY_PREFIX         — key prefix inside the bucket (default: "audit_worm/")
    WORM_S3_REGION             — AWS region (default: "us-east-1")
    WORM_S3_RETENTION_DAYS     — Object Lock COMPLIANCE retention days (default: 2557 ≈ 7 yr)
    AUDIT_ANCHOR_HMAC_KEY      — hex- or base64-encoded 32-byte key for daily digest signing
    AUDIT_ANCHOR_WEBHOOK_URL   — optional HTTPS POST endpoint to receive the daily anchor JSON
    AUDIT_LOCAL_LOG_PATH       — override path for the local log file (default: runs/audit_worm.log)

Finding addressed: 9.4 / C01 — audit log WORM guarantees must extend beyond a single
host's filesystem.  S3 + Object Lock COMPLIANCE provides immutability enforced by the
cloud provider.  The daily HMAC anchor lets external parties verify log continuity without
having read access to individual records.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

_log = logging.getLogger("shopsquire.worm")

_LOCAL_LOG_PATH = os.getenv("AUDIT_LOCAL_LOG_PATH", "runs/audit_worm.log")


# ──────────────────────────────────────────────────────────────────────────────
# Public helpers
# ──────────────────────────────────────────────────────────────────────────────

def append_worm_record(category: str, payload: Dict[str, Any]) -> None:
    """Append one JSON record to the local WORM log and — if configured — to S3."""
    try:
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "payload": payload,
        }
        _write_local(record)
        _upload_to_s3_worm(record)
    except Exception:
        pass


def publish_daily_audit_anchor(date: datetime | None = None) -> Dict[str, Any] | None:
    """Compute and publish the daily HMAC-SHA256 anchor for audit continuity.

    Reads all records logged today from the local log, computes an HMAC-SHA256 digest
    over their canonical JSON representations, then:
      1. Uploads the anchor document to S3 WORM (if WORM_S3_BUCKET is set).
      2. POSTs the anchor JSON to AUDIT_ANCHOR_WEBHOOK_URL (if set).
      3. Returns the anchor document dict.

    The anchor document is itself also appended to the local log and S3 so the
    chain is self-verifying.
    """
    today = (date or datetime.now(timezone.utc)).date()
    records = _read_records_for_date(today)
    if not records:
        _log.debug("No WORM records for %s; skipping anchor", today)
        return None

    digest = _compute_hmac_digest(records)
    anchor = {
        "type": "daily_audit_anchor",
        "date": today.isoformat(),
        "record_count": len(records),
        "sha256_hmac": digest,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }

    # Self-log the anchor (so anchors are themselves in the WORM chain)
    _write_local(anchor)
    _upload_to_s3_worm(anchor, key_suffix=f"anchors/{today.isoformat()}.json")
    _post_anchor_webhook(anchor)

    _log.info("Daily audit anchor published: date=%s records=%d", today, len(records))
    return anchor


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _write_local(record: Dict[str, Any]) -> None:
    """Append record as JSON line to the local log file."""
    try:
        os.makedirs(os.path.dirname(_LOCAL_LOG_PATH) or ".", exist_ok=True)
        with open(_LOCAL_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception as exc:
        _log.debug("WORM local write failed: %s", exc)


def _upload_to_s3_worm(
    record: Dict[str, Any],
    key_suffix: str | None = None,
) -> None:
    """Upload record to S3 with Object Lock COMPLIANCE mode.

    Silently skips if:
    - WORM_S3_BUCKET is not set, OR
    - boto3 is not installed, OR
    - any S3 error occurs (failures must never block the application).
    """
    bucket = os.getenv("WORM_S3_BUCKET", "").strip()
    if not bucket:
        return
    try:
        from src.app.providers.aws import get_client
    except ImportError:
        _log.debug("boto3 not installed; S3 WORM upload skipped")
        return

    try:
        region = os.getenv("WORM_S3_REGION", "us-east-1")
        prefix = os.getenv("WORM_S3_KEY_PREFIX", "audit_worm/").rstrip("/") + "/"
        retention_days = int(os.getenv("WORM_S3_RETENTION_DAYS", "2557"))

        if key_suffix:
            key = f"{prefix}{key_suffix}"
        else:
            # Partition records by UTC date for efficient future retrieval
            ts = record.get("time", datetime.now(timezone.utc).isoformat())
            date_part = ts[:10] if isinstance(ts, str) else datetime.now(timezone.utc).strftime("%Y-%m-%d")
            time_us = datetime.now(timezone.utc).strftime("%H%M%S%f")
            key = f"{prefix}{date_part}/{time_us}.json"

        retain_until = (datetime.now(timezone.utc) + timedelta(days=retention_days)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        body = json.dumps(record, ensure_ascii=False, sort_keys=True).encode()

        client = get_client("s3", region_name=region)
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
            ObjectLockMode="COMPLIANCE",
            ObjectLockRetainUntilDate=retain_until,
        )
        _log.debug("WORM S3 upload: s3://%s/%s (retain until %s)", bucket, key, retain_until)
    except Exception as exc:
        # S3 failure must never surface to callers
        _log.warning("WORM S3 upload failed: %s", exc)


def _read_records_for_date(date: "datetime.date") -> list[Dict[str, Any]]:
    """Return all log records whose 'time' field falls on *date* (UTC)."""
    records: list[Dict[str, Any]] = []
    try:
        with open(_LOCAL_LOG_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    ts = obj.get("time", "")
                    if isinstance(ts, str) and ts[:10] == date.isoformat():
                        records.append(obj)
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        pass
    except Exception as exc:
        _log.debug("WORM read_records_for_date error: %s", exc)
    return records


def _compute_hmac_digest(records: list[Dict[str, Any]]) -> str:
    """Compute HMAC-SHA256 over the concatenated canonical JSON of *records*.

    Key is read from AUDIT_ANCHOR_HMAC_KEY (hex- or base64-encoded 32 bytes).
    Falls back to a zero-byte key when not set — digest is still useful for
    integrity checking even without authentication.
    """
    raw_key = _load_hmac_key()
    separator = b"\n"
    h = hmac.new(raw_key, digestmod=hashlib.sha256)
    for rec in records:
        h.update(json.dumps(rec, ensure_ascii=False, sort_keys=True).encode())
        h.update(separator)
    return h.hexdigest()


def _load_hmac_key() -> bytes:
    """Load AUDIT_ANCHOR_HMAC_KEY from env; return 32 zero bytes if unset."""
    raw = os.getenv("AUDIT_ANCHOR_HMAC_KEY", "").strip()
    if not raw:
        return b"\x00" * 32
    # Try hex first, then base64
    try:
        key = bytes.fromhex(raw)
        if len(key) >= 16:
            return key
    except ValueError:
        pass
    try:
        import base64
        key = base64.b64decode(raw)
        if len(key) >= 16:
            return key
    except Exception:
        pass
    return raw.encode()[:64]


def _post_anchor_webhook(anchor: Dict[str, Any]) -> None:
    """POST anchor JSON to AUDIT_ANCHOR_WEBHOOK_URL if configured."""
    url = os.getenv("AUDIT_ANCHOR_WEBHOOK_URL", "").strip()
    if not url:
        return
    if not url.startswith("https://"):
        _log.warning("AUDIT_ANCHOR_WEBHOOK_URL must use HTTPS; skipping POST")
        return
    try:
        import httpx
        resp = httpx.post(url, json=anchor, timeout=10)
        resp.raise_for_status()
        _log.debug("Audit anchor webhook delivered: status=%d", resp.status_code)
    except Exception as exc:
        _log.warning("Audit anchor webhook POST failed: %s", exc)
