"""9.4 / C01 — Tests for WORM audit log S3 anchor and HMAC digest verification.

Coverage:
- append_worm_record writes to local log
- append_worm_record calls S3 upload with Object Lock params when bucket is set
- publish_daily_audit_anchor returns anchor with correct record_count and date
- HMAC digest is deterministic and changes when records change
- Webhook delivery is attempted when AUDIT_ANCHOR_WEBHOOK_URL is set
- Graceful degradation: missing boto3 / missing env / S3 error never raises
- Anchor is self-logged (chain continuity)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _worm_module():
    """Import (or reimport) worm to pick up changed env vars."""
    import importlib
    import src.app.observability.worm as m
    importlib.reload(m)
    return m


def _write_log(path: Path, records: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, sort_keys=True) + "\n")


def _make_record(date: str, category: str = "test", payload: dict | None = None) -> dict:
    return {
        "time": f"{date}T12:00:00+00:00",
        "category": category,
        "payload": payload or {"k": "v"},
    }


# ---------------------------------------------------------------------------
# append_worm_record: local file
# ---------------------------------------------------------------------------

def test_append_writes_json_line(tmp_path):
    log_path = tmp_path / "audit_worm.log"
    with patch.dict(os.environ, {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": ""}):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        worm.append_worm_record("test_category", {"key": "value"})

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["category"] == "test_category"
    assert obj["payload"]["key"] == "value"
    assert "time" in obj


def test_append_multiple_records(tmp_path):
    log_path = tmp_path / "audit_worm.log"
    with patch.dict(os.environ, {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": ""}):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        for i in range(5):
            worm.append_worm_record("cat", {"i": i})

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 5


def test_append_creates_directory(tmp_path):
    log_path = tmp_path / "nested" / "dir" / "audit_worm.log"
    with patch.dict(os.environ, {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": ""}):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        worm.append_worm_record("x", {})

    assert log_path.exists()


# ---------------------------------------------------------------------------
# append_worm_record: S3 upload with Object Lock
# ---------------------------------------------------------------------------

def test_s3_upload_called_with_object_lock(tmp_path):
    log_path = tmp_path / "audit_worm.log"
    mock_client = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_botocore = MagicMock()
    mock_botocore.exceptions.BotoCoreError = Exception
    mock_botocore.exceptions.ClientError = Exception

    with patch.dict(
        os.environ,
        {
            "AUDIT_LOCAL_LOG_PATH": str(log_path),
            "WORM_S3_BUCKET": "my-audit-bucket",
            "WORM_S3_KEY_PREFIX": "audit/",
            "WORM_S3_REGION": "eu-west-1",
            "WORM_S3_RETENTION_DAYS": "30",
        },
    ), patch.dict(
        "sys.modules",
        {"boto3": mock_boto3, "botocore": mock_botocore, "botocore.exceptions": mock_botocore.exceptions},
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        worm.append_worm_record("billing", {"amount": 100})

    assert mock_boto3.client.called
    assert mock_client.put_object.called
    kwargs = mock_client.put_object.call_args[1]
    assert kwargs["Bucket"] == "my-audit-bucket"
    assert kwargs["ObjectLockMode"] == "COMPLIANCE"
    assert "ObjectLockRetainUntilDate" in kwargs
    # Verify key is under the right prefix
    assert kwargs["Key"].startswith("audit/")
    # Verify body is valid JSON
    body = json.loads(kwargs["Body"])
    assert body["category"] == "billing"


def test_s3_upload_skipped_when_no_bucket(tmp_path):
    log_path = tmp_path / "audit_worm.log"
    mock_boto3 = MagicMock()
    with patch.dict(
        os.environ, {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": ""}
    ), patch.dict("sys.modules", {"boto3": mock_boto3}):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        worm.append_worm_record("x", {})

    mock_boto3.client.assert_not_called()


def test_s3_upload_does_not_raise_on_error(tmp_path):
    log_path = tmp_path / "audit_worm.log"
    mock_client = MagicMock()
    mock_client.put_object.side_effect = Exception("AccessDenied")
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_botocore = MagicMock()
    mock_botocore.exceptions.BotoCoreError = Exception
    mock_botocore.exceptions.ClientError = Exception

    with patch.dict(
        os.environ,
        {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": "locked-bucket"},
    ), patch.dict(
        "sys.modules",
        {"boto3": mock_boto3, "botocore": mock_botocore, "botocore.exceptions": mock_botocore.exceptions},
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        # Must NOT raise even though S3 fails
        worm.append_worm_record("critical", {"data": "x"})

    # Local log still written
    assert log_path.exists()


def test_boto3_missing_does_not_raise(tmp_path):
    log_path = tmp_path / "audit_worm.log"
    with patch.dict(
        os.environ,
        {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": "some-bucket"},
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)

        import builtins
        real_import = builtins.__import__

        def import_no_boto3(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("boto3 not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_no_boto3):
            worm.append_worm_record("x", {})  # must not raise


# ---------------------------------------------------------------------------
# publish_daily_audit_anchor
# ---------------------------------------------------------------------------

def test_publish_anchor_correct_record_count(tmp_path):
    today = datetime.now(timezone.utc).date()
    log_path = tmp_path / "audit_worm.log"
    today_str = today.isoformat()
    records = [_make_record(today_str) for _ in range(7)]
    # Add a record from yesterday — should not be counted
    yesterday_str = (today - timedelta(days=1)).isoformat()
    records.append(_make_record(yesterday_str, category="old"))
    _write_log(log_path, records)

    with patch.dict(
        os.environ,
        {
            "AUDIT_LOCAL_LOG_PATH": str(log_path),
            "WORM_S3_BUCKET": "",
            "AUDIT_ANCHOR_HMAC_KEY": "",
        },
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)

        anchor = worm.publish_daily_audit_anchor()

    assert anchor is not None
    assert anchor["record_count"] == 7
    assert anchor["date"] == today_str
    assert "sha256_hmac" in anchor
    assert len(anchor["sha256_hmac"]) == 64  # hex-encoded SHA256


def test_publish_anchor_returns_none_when_no_records(tmp_path):
    log_path = tmp_path / "audit_worm.log"
    log_path.write_text("")  # empty file

    with patch.dict(
        os.environ,
        {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": ""},
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)

        result = worm.publish_daily_audit_anchor()

    assert result is None


def test_publish_anchor_log_missing_returns_none(tmp_path):
    log_path = tmp_path / "nonexistent.log"  # doesn't exist

    with patch.dict(
        os.environ,
        {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": ""},
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)

        result = worm.publish_daily_audit_anchor()

    assert result is None


def test_publish_anchor_self_logged(tmp_path):
    """The anchor JSON is appended to the local log for chain continuity."""
    today = datetime.now(timezone.utc).date()
    log_path = tmp_path / "audit_worm.log"
    _write_log(log_path, [_make_record(today.isoformat())])

    with patch.dict(
        os.environ,
        {"AUDIT_LOCAL_LOG_PATH": str(log_path), "WORM_S3_BUCKET": ""},
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        worm.publish_daily_audit_anchor()

    lines = log_path.read_text().strip().splitlines()
    anchor_lines = [l for l in lines if "daily_audit_anchor" in l]
    assert len(anchor_lines) == 1


def test_publish_anchor_s3_key_in_anchors_prefix(tmp_path):
    """Anchor is uploaded under anchors/ sub-prefix in S3."""
    today = datetime.now(timezone.utc).date()
    log_path = tmp_path / "audit_worm.log"
    _write_log(log_path, [_make_record(today.isoformat())])
    mock_client = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_client
    mock_botocore = MagicMock()
    mock_botocore.exceptions.BotoCoreError = Exception
    mock_botocore.exceptions.ClientError = Exception

    with patch.dict(
        os.environ,
        {
            "AUDIT_LOCAL_LOG_PATH": str(log_path),
            "WORM_S3_BUCKET": "audit-bucket",
            "WORM_S3_KEY_PREFIX": "worm/",
        },
    ), patch.dict(
        "sys.modules",
        {"boto3": mock_boto3, "botocore": mock_botocore, "botocore.exceptions": mock_botocore.exceptions},
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        worm.publish_daily_audit_anchor()

    calls = mock_client.put_object.call_args_list
    anchor_call = next(
        (c for c in calls if "anchors/" in c[1].get("Key", "")), None
    )
    assert anchor_call is not None
    assert today.isoformat() in anchor_call[1]["Key"]


# ---------------------------------------------------------------------------
# HMAC digest correctness
# ---------------------------------------------------------------------------

def test_hmac_digest_deterministic():
    import importlib
    import src.app.observability.worm as worm
    importlib.reload(worm)

    records = [_make_record("2025-06-01") for _ in range(3)]
    d1 = worm._compute_hmac_digest(records)
    d2 = worm._compute_hmac_digest(records)
    assert d1 == d2


def test_hmac_digest_changes_with_records():
    import importlib
    import src.app.observability.worm as worm
    importlib.reload(worm)

    r1 = [_make_record("2025-06-01", payload={"a": 1})]
    r2 = [_make_record("2025-06-01", payload={"a": 2})]
    assert worm._compute_hmac_digest(r1) != worm._compute_hmac_digest(r2)


def test_hmac_key_loaded_from_hex_env(tmp_path):
    key_hex = os.urandom(32).hex()
    with patch.dict(os.environ, {"AUDIT_ANCHOR_HMAC_KEY": key_hex}):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        key = worm._load_hmac_key()
    assert key == bytes.fromhex(key_hex)


def test_hmac_key_falls_back_to_zero(tmp_path):
    with patch.dict(os.environ, {"AUDIT_ANCHOR_HMAC_KEY": ""}):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)
        key = worm._load_hmac_key()
    assert key == b"\x00" * 32


# ---------------------------------------------------------------------------
# Webhook delivery
# ---------------------------------------------------------------------------

def test_anchor_webhook_posted_when_url_set(tmp_path):
    today = datetime.now(timezone.utc).date()
    log_path = tmp_path / "audit_worm.log"
    _write_log(log_path, [_make_record(today.isoformat())])

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()

    with patch.dict(
        os.environ,
        {
            "AUDIT_LOCAL_LOG_PATH": str(log_path),
            "WORM_S3_BUCKET": "",
            "AUDIT_ANCHOR_WEBHOOK_URL": "https://compliance.example.corp/anchor",
        },
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)

        with patch("httpx.post", return_value=mock_response) as mock_post:
            worm.publish_daily_audit_anchor()

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == "https://compliance.example.corp/anchor"
    posted_json = call_kwargs[1]["json"]
    assert posted_json["type"] == "daily_audit_anchor"


def test_anchor_webhook_http_rejected(tmp_path):
    """HTTP (non-HTTPS) webhook URLs must be rejected silently."""
    today = datetime.now(timezone.utc).date()
    log_path = tmp_path / "audit_worm.log"
    _write_log(log_path, [_make_record(today.isoformat())])

    with patch.dict(
        os.environ,
        {
            "AUDIT_LOCAL_LOG_PATH": str(log_path),
            "WORM_S3_BUCKET": "",
            "AUDIT_ANCHOR_WEBHOOK_URL": "http://insecure.corp/anchor",
        },
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)

        with patch("httpx.post") as mock_post:
            worm.publish_daily_audit_anchor()

    mock_post.assert_not_called()


def test_anchor_webhook_failure_does_not_raise(tmp_path):
    today = datetime.now(timezone.utc).date()
    log_path = tmp_path / "audit_worm.log"
    _write_log(log_path, [_make_record(today.isoformat())])

    with patch.dict(
        os.environ,
        {
            "AUDIT_LOCAL_LOG_PATH": str(log_path),
            "WORM_S3_BUCKET": "",
            "AUDIT_ANCHOR_WEBHOOK_URL": "https://down.example.corp/anchor",
        },
    ):
        import importlib
        import src.app.observability.worm as worm
        importlib.reload(worm)

        with patch("httpx.post", side_effect=Exception("connection refused")):
            result = worm.publish_daily_audit_anchor()  # must NOT raise

    assert result is not None
