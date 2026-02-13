import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.models.db import set_engine
from src.app.data_readiness.report import compute_inventory_readiness
from src.app.services.inventory_agent import InventoryAgent, ReorderRecommendation


def test_inventory_readiness_empty_db_is_bad(tmp_path):
    db_path = tmp_path / "inv.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    rep = compute_inventory_readiness(freshness_hours=1)
    assert rep.level in ("warn", "bad")
    assert rep.score < 0.8


def test_inventory_execute_reorder_blocks_on_readiness(tmp_path, monkeypatch):
    db_path = tmp_path / "inv2.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    monkeypatch.setenv("INVENTORY_DATA_READINESS_REQUIRED", "1")
    monkeypatch.setenv("INVENTORY_DATA_READINESS_MIN_SCORE", "0.9")
    rec = ReorderRecommendation(sku="SKU1", supplier_id=None, quantity=10, estimated_cost=100.0, lead_time_days=7, urgency="normal")
    out = InventoryAgent().execute_reorder(rec)
    assert out.get("status") == "data_not_ready"

