"""KYV vendor dedup — re-onboarding the same domain UPDATES the vendor, never creates a duplicate."""
from __future__ import annotations

import contextlib

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def kyv(monkeypatch):
    from src.app.security import kyv_registry as k
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Session = sessionmaker(bind=eng, future=True)

    @contextlib.contextmanager
    def _sess():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    monkeypatch.setattr(k, "db_session", _sess)
    return k, eng


def _count(eng, domain: str) -> int:
    with eng.connect() as c:
        return int(c.execute(text("SELECT COUNT(*) FROM kyv_vendors WHERE verified_domain=:d"),
                             {"d": domain}).scalar() or 0)


def test_same_domain_registers_once_then_dedupes(kyv):
    k, eng = kyv
    a = k.register_vendor(tenant_id="t1", legal_name="CreatorFleet Wholesale Pty Ltd",
                          verified_domain="creatorfleet.example", risk_tier="low")
    b = k.register_vendor(tenant_id="t1", legal_name="CreatorFleet Wholesale (updated)",
                          verified_domain="CreatorFleet.Example", risk_tier="low")  # case-insensitive same domain
    assert a["ok"] and b["ok"]
    assert a.get("deduped") is False and b.get("deduped") is True
    assert b["vendor_id"] == a["vendor_id"]                # same vendor, not a new row
    assert _count(eng, "creatorfleet.example") == 1        # exactly ONE row for the domain
    # the update took effect
    v = k.lookup_vendor_by_domain(tenant_id="t1", domain="creatorfleet.example")
    assert v and v["legal_name"] == "CreatorFleet Wholesale (updated)"


def test_different_domains_are_distinct(kyv):
    k, eng = kyv
    k.register_vendor(tenant_id="t1", legal_name="A", verified_domain="a.example")
    k.register_vendor(tenant_id="t1", legal_name="B", verified_domain="b.example")
    assert _count(eng, "a.example") == 1 and _count(eng, "b.example") == 1


def test_same_domain_different_tenant_not_deduped(kyv):
    k, eng = kyv
    r1 = k.register_vendor(tenant_id="t1", legal_name="A", verified_domain="shared.example")
    r2 = k.register_vendor(tenant_id="t2", legal_name="A", verified_domain="shared.example")
    assert r1["vendor_id"] != r2["vendor_id"] and r2.get("deduped") is False  # tenant-scoped
