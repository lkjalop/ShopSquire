"""Generic profile-driven catalog seeder — the per-vertical seed that makes a switched store run
real DB retrieval instead of the zero-result fallback. Vertical-blind: reads the profile slot."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def db(monkeypatch):
    eng = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False},
                        poolclass=StaticPool, future=True)
    import src.app.models.db as _dbmod
    orig = _dbmod.engine
    _dbmod.engine = eng
    _dbmod.set_engine(eng)
    with eng.begin() as c:
        c.execute(text("CREATE TABLE products (id TEXT PRIMARY KEY, sku TEXT, name TEXT, price_cents INTEGER, "
                       "currency TEXT, specs TEXT, active INTEGER, updated_at TEXT, image_url TEXT)"))
        c.execute(text("CREATE TABLE inventory (id TEXT PRIMARY KEY, product_id TEXT, stock INTEGER, "
                       "warehouse TEXT, updated_at TEXT)"))
    from src.app.models.db import db_session
    with db_session() as s:
        yield s
    _dbmod.engine = orig
    _dbmod.set_engine(orig)


@pytest.mark.parametrize("profile_id", ["fashion", "pharmacy"])
def test_seed_is_idempotent_and_stocks(db, profile_id):
    from scripts.seed_profile_catalog import seed_profile_catalog
    n1 = seed_profile_catalog(db, profile_id)
    db.commit()
    assert n1 >= 6, f"{profile_id} should seed a credible catalog"
    # every product got exactly one inventory row (the out_of_stock fix)
    prod = db.execute(text("SELECT COUNT(*) FROM products")).scalar()
    inv = db.execute(text("SELECT COUNT(*) FROM inventory")).scalar()
    assert prod == n1 and inv == n1
    # re-run adds nothing (idempotent per SKU)
    n2 = seed_profile_catalog(db, profile_id)
    db.commit()
    assert n2 == 0
    assert db.execute(text("SELECT COUNT(*) FROM products")).scalar() == n1


def test_prices_and_stock_are_positive(db):
    from scripts.seed_profile_catalog import seed_profile_catalog
    seed_profile_catalog(db, "fashion")
    db.commit()
    bad = db.execute(text("SELECT COUNT(*) FROM products WHERE price_cents <= 0")).scalar()
    oos = db.execute(text("SELECT COUNT(*) FROM inventory WHERE stock <= 0")).scalar()
    assert bad == 0 and oos == 0
