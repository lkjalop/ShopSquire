from fastapi.testclient import TestClient
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import os, pathlib, json
import src.app.models.db as dbmod
from src.app.main import create_app

# setup tmp db as in test
tmp_db = 'test_sqlite_storefront.sqlite'
os.environ['DATABASE_URL'] = f"sqlite+pysqlite:///{tmp_db}"
engine = create_engine(f"sqlite+pysqlite:///{tmp_db}", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
SessionLocal = sessionmaker(bind=engine, future=True)
dbmod.engine = engine
dbmod.SessionLocal = SessionLocal

# apply schema
schema_path = pathlib.Path('db/schema.sql')
sql = schema_path.read_text(encoding='utf-8')
statements = [s.strip() for s in sql.split(';') if s.strip()]
with engine.connect() as conn:
    for stmt in statements:
        conn.execute(text(stmt))
    conn.commit()

# seed product
with engine.begin() as conn:
    conn.execute(
        text("INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at) VALUES ('p1', 'SKU-UI', 'UI Laptop', 129900, 'USD', :specs, true, CURRENT_TIMESTAMP)"),
        {"specs": '{"graphics":"Intel Iris","wifi":"Wi-Fi 6","ports":["1 x HDMI","2 x USB-C"],"ram_gb":16,"storage":"512GB","cpu":"Intel Core i5","rating":4.4,"shipping_days":3}'}
    )
    conn.execute(text("INSERT INTO inventory (id, product_id, stock, warehouse, updated_at) VALUES ('inv1','p1', 4, 'default', CURRENT_TIMESTAMP)"))

app = create_app()
client = TestClient(app)
r = client.get('/ui/storefront')
print('STATUS', r.status_code)
print(r.text)
