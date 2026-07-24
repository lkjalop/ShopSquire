from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import src.app.services.bi_intelligence as bi


def _session(monkeypatch):
    session = sessionmaker(
        bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    session.execute(text("""
        CREATE TABLE marketing_event_fact (
          tenant_id TEXT, event_type TEXT, subject_hash TEXT, sku TEXT,
          value INTEGER, quantity INTEGER, currency TEXT, occurred_at TEXT,
          status TEXT
        )
    """))
    now = datetime.now(timezone.utc).isoformat()
    session.execute(text("""
        INSERT INTO marketing_event_fact VALUES
          ('tenant-a','purchase','u1','SKU-A',10000,1,'AUD',:now,'active'),
          ('tenant-b','purchase','u2','SKU-B',900000,1,'USD',:now,'active')
    """), {"now": now})
    session.commit()

    @contextmanager
    def scoped():
        yield session

    monkeypatch.setattr(bi, "db_session", scoped)
    return session


def test_margin_and_rfm_are_tenant_scoped_and_do_not_fabricate_cost(monkeypatch):
    session = _session(monkeypatch)
    margin = bi.margin_intelligence(tenant_id="tenant-a")
    assert [row["sku"] for row in margin["top"]] == ["SKU-A"]
    assert margin["top"][0]["margin_cents"] is None
    assert margin["top"][0]["economics_reason"] == "matched_landed_cogs_required"
    rfm = bi.clv_prediction(tenant_id="tenant-a")
    assert [row["uid_hash"] for row in rfm["users"]] == ["u1"]
    assert rfm["status"] == "estimated"
    session.close()


def test_tenant_id_is_mandatory():
    import pytest
    with pytest.raises(ValueError, match="tenant_id"):
        bi.margin_intelligence(tenant_id="")
