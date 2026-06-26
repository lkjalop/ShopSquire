"""Step 8 — deterministic, tenant-isolated market replay through the REAL M3 path."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.services import market_replay as mr
from src.app.services.market_analysis import load_recent_findings


@pytest.fixture()
def db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    s = sessionmaker(bind=eng, future=True)()
    try:
        yield s
    finally:
        s.close()


def test_load_run_produces_findings():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    db = sessionmaker(bind=eng, future=True)()
    mr.load_days(db, up_to_day=mr.TOTAL_DAYS)
    out = mr.run(db)
    assert out["persisted"] >= 1
    st = mr.state(db)
    types = {f["type"] for f in st["findings"]}
    # the spike + the catalog gap both surface from the synthetic 7-day curve
    assert "demand_shift" in types
    assert "inventory_demand_mismatch" in types
    assert st["signals"] > 0 and st["label"] == "SYNTHETIC REPLAY"


def test_replay_is_tenant_isolated(db):
    mr.load_days(db, up_to_day=mr.TOTAL_DAYS)
    mr.run(db)
    # the real 'default' tenant sees NONE of the replay's findings
    assert load_recent_findings(db, tenant_id="default") == []
    # and no replay signals leak into the default tenant
    default_sigs = db.execute(text("SELECT COUNT(*) FROM market_signal WHERE tenant_id='default'")).scalar()
    replay_sigs = db.execute(text("SELECT COUNT(*) FROM market_signal WHERE tenant_id=:t"),
                             {"t": mr.REPLAY_TENANT}).scalar()
    assert default_sigs == 0 and replay_sigs > 0


def test_advancing_days_changes_findings(db):
    # days 1-5 are calm (no spike) → no demand_shift yet
    mr.load_days(db, up_to_day=5)
    mr.run(db)
    early = {f["type"] for f in mr.state(db)["findings"]}
    assert "demand_shift" not in early
    # advance to day 7 → the spike + gap appear
    mr.load_days(db, up_to_day=mr.TOTAL_DAYS)
    mr.run(db)
    late = {f["type"] for f in mr.state(db)["findings"]}
    assert "demand_shift" in late


def test_heat_day_surfaces_competitor_and_objection_findings(db):
    # before the heat day (≤5) no competitor/objection signals exist
    mr.load_days(db, up_to_day=5)
    mr.run(db)
    early = {f["type"] for f in mr.state(db)["findings"]}
    assert "competitor_undercut" not in early and "objection_cluster" not in early
    # advance through the full curve → the rival undercut + objection cluster appear
    mr.load_days(db, up_to_day=mr.TOTAL_DAYS)
    mr.run(db)
    late = {f["type"] for f in mr.state(db)["findings"]}
    assert "competitor_undercut" in late and "objection_cluster" in late


def test_reset_clears(db):
    mr.load_days(db, up_to_day=mr.TOTAL_DAYS)
    mr.run(db)
    mr.reset(db)
    assert mr.state(db)["signals"] == 0 and mr.state(db)["active_findings"] == 0
