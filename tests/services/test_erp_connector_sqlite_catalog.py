import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

from src.app.models.db import set_engine, db_session
from src.app.erp.connectors.sqlite_catalog import SQLiteCatalogConnector


def test_sqlite_catalog_connector_fetches_inventory(tmp_path):
    db_path = tmp_path / "erp.sqlite"
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{db_path}"
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod
        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass

    # Insert one product + inventory row
    with db_session() as db:
        pid = "p1"
        db.execute(text("INSERT OR REPLACE INTO products (id, sku, name, price_cents, active) VALUES (:id, :sku, :name, 100, 1)"), {"id": pid, "sku": "SKU1", "name": "Test"})
        db.execute(text("INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse) VALUES ('i1', :pid, 7, 'default')"), {"pid": pid})
        db.commit()

    recs = SQLiteCatalogConnector().fetch_inventory()
    assert len(recs) == 1
    assert recs[0].sku == "SKU1"
    assert recs[0].stock == 7

