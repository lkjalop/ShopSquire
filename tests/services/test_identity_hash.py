"""0.3 — identity pseudonym must be consistent, salted-when-configured, tenant-scoped."""
from __future__ import annotations

from src.app.deps import hash_uid


def test_consistent_length_16():
    assert len(hash_uid("user-123")) == 16
    assert len(hash_uid("")) == 16


def test_deterministic_same_input_same_output():
    assert hash_uid("user-123") == hash_uid("user-123")


def test_unsalted_default_is_plain_sha256(monkeypatch):
    monkeypatch.delenv("IDENTITY_HASH_SECRET", raising=False)
    monkeypatch.delenv("AUDIT_CHAIN_SECRET", raising=False)
    import hashlib
    assert hash_uid("abc") == hashlib.sha256(b"abc").hexdigest()[:16]


def test_salt_changes_output_and_is_not_plain_sha256(monkeypatch):
    monkeypatch.setenv("IDENTITY_HASH_SECRET", "s3cr3t-salt")
    import hashlib
    salted = hash_uid("abc")
    assert salted != hashlib.sha256(b"abc").hexdigest()[:16]
    assert len(salted) == 16


def test_tenant_scope_prevents_collision(monkeypatch):
    monkeypatch.delenv("IDENTITY_HASH_SECRET", raising=False)
    monkeypatch.delenv("AUDIT_CHAIN_SECRET", raising=False)
    a = hash_uid("u1", tenant_id="store_a")
    b = hash_uid("u1", tenant_id="store_b")
    assert a != b


def test_recommend_and_pricing_use_same_pseudonym():
    # Both routes now call hash_uid -> same value for the same user (was [:12] vs [:16]).
    import src.app.routers.recommend as rec
    import src.app.routers.pricing as pr
    assert hasattr(rec, "hash_uid") and hasattr(pr, "hash_uid")
    assert rec.hash_uid("u-xyz") == pr.hash_uid("u-xyz")
