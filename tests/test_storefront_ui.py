import os
import pathlib

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.app.models.db as dbmod
from src.app.main import create_app
from tests.utils import default_headers


tmp_db = "test_sqlite_storefront.sqlite"
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{tmp_db}")
os.environ.setdefault("FEATURE_FLAGS_PATH", "config/feature_flags.json")

engine = create_engine(
    f"sqlite+pysqlite:///{tmp_db}",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, future=True)
dbmod.engine = engine
dbmod.SessionLocal = SessionLocal

app = create_app()
client = TestClient(app, headers=default_headers())


def _apply_schema():
    schema_path = pathlib.Path("db/schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()


def _seed_product():
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at) "
                "VALUES ('p1', 'SKU-UI', 'UI Laptop', 129900, 'USD', :specs, true, CURRENT_TIMESTAMP)"
            ),
            {
                "specs": '{"graphics":"Intel Iris","wifi":"Wi-Fi 6","ports":["1 x HDMI","2 x USB-C"],"ram_gb":16,"storage":"512GB","cpu":"Intel Core i5","rating":4.4,"shipping_days":3}',
            },
        )
        conn.execute(
            text("INSERT INTO inventory (id, product_id, stock, warehouse, updated_at) VALUES ('inv1','p1', 4, 'default', CURRENT_TIMESTAMP)")
        )


def test_storefront_cards_include_specs():
    _apply_schema()
    _seed_product()
    r = client.get("/ui/storefront")
    assert r.status_code == 200
    html = r.text
    assert "GPU" in html or "Graphics" in html
    assert "Wi-Fi" in html
    assert "Ports" in html


def test_product_detail_shows_features():
    _apply_schema()
    _seed_product()
    r = client.get("/ui/product/SKU-UI")
    assert r.status_code == 200
    html = r.text
    assert "Intel Iris" in html
    assert "Wi-Fi 6" in html
    assert "Ports" in html


def test_forensics_console_route_exists():
    r = client.get("/ui/forensics")
    assert r.status_code == 200
    assert "Forensics Console" in r.text
