"""Tests for OOB verification service."""
import time

import pytest

from src.app.security.oob_verification import (
    OOBChannel,
    OOBStatus,
    confirm_verification,
    create_verification,
    deny_verification,
    get_verification,
    list_pending,
    requires_oob,
    _store,
)


@pytest.fixture(autouse=True)
def _clear_store():
    _store.clear()
    yield
    _store.clear()


def test_create_and_confirm():
    result = create_verification(
        vendor_domain="supplier.com",
        trigger_signal="bank_fingerprint_baseline_mismatch",
        channel=OOBChannel.EMAIL,
        destination="finance@supplier.com",
    )
    assert result["status"] in ("pending", "sent")
    assert result["token"]
    request_id = result["request_id"]

    # Confirm with correct token
    conf = confirm_verification(request_id, result["token"])
    assert conf["ok"] is True
    assert conf["status"] == OOBStatus.CONFIRMED.value


def test_wrong_token_then_correct():
    result = create_verification(
        vendor_domain="vendor.co",
        trigger_signal="account_name_mismatch",
    )
    request_id = result["request_id"]

    # Wrong token
    bad = confirm_verification(request_id, "wrong")
    assert bad["ok"] is False
    assert bad["error"] == "invalid_token"

    # Right token still works
    good = confirm_verification(request_id, result["token"])
    assert good["ok"] is True


def test_max_attempts():
    result = create_verification(
        vendor_domain="bad.co",
        trigger_signal="bank_fingerprint_extracted_mismatch",
    )
    rid = result["request_id"]
    for _ in range(5):
        confirm_verification(rid, "wrong")
    denied = confirm_verification(rid, result["token"])
    assert denied["ok"] is False
    assert denied["error"] == "already_resolved"


def test_deny():
    result = create_verification(
        vendor_domain="test.co",
        trigger_signal="vendor_homoglyph_impersonation",
    )
    d = deny_verification(result["request_id"])
    assert d["ok"] is True
    assert d["status"] == OOBStatus.DENIED.value


def test_expired(monkeypatch):
    result = create_verification(
        vendor_domain="expired.co",
        trigger_signal="bank_fingerprint_baseline_mismatch",
    )
    rid = result["request_id"]
    # Force expiry
    _store[rid]["expires_at"] = time.time() - 1
    exp = confirm_verification(rid, result["token"])
    assert exp["ok"] is False
    assert exp["error"] == "expired"


def test_get_verification():
    result = create_verification(
        vendor_domain="look.co",
        trigger_signal="account_name_mismatch",
    )
    record = get_verification(result["request_id"])
    assert record is not None
    assert record["vendor_domain"] == "look.co"
    assert "token_hash" not in record


def test_list_pending():
    create_verification(vendor_domain="a.co", trigger_signal="x")
    create_verification(vendor_domain="b.co", trigger_signal="y")
    pending = list_pending()
    assert len(pending) >= 2

    filtered = list_pending(vendor_domain="a.co")
    assert all(r["vendor_domain"] == "a.co" for r in filtered)


def test_requires_oob():
    assert requires_oob([{"type": "bank_fingerprint_baseline_mismatch"}]) is True
    assert requires_oob([{"type": "account_name_mismatch"}]) is True
    assert requires_oob([{"type": "vendor_homoglyph_impersonation"}]) is True
    assert requires_oob([{"type": "urgency_detected"}]) is False
    assert requires_oob([]) is False
