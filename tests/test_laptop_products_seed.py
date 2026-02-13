import pathlib

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts.seed_demo_data import parse_laptop_products, seed_products


def _apply_schema(engine):
    schema_path = pathlib.Path("db/schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()


def test_parse_laptop_products_has_prices():
    products = parse_laptop_products()
    assert products, "Expected laptop-products.txt to yield products"
    assert all(p.get("name") and p.get("price_cents", 0) > 0 for p in products)


def test_seed_products_from_laptops():
    engine = create_engine("sqlite:///:memory:", future=True)
    _apply_schema(engine)
    Session = sessionmaker(bind=engine, future=True)
    expected = len(parse_laptop_products()) or 5
    with Session() as db:
        seed_products(db)
        db.commit()
        count = db.execute(text("SELECT COUNT(*) FROM products")).scalar()
        assert count and count >= expected
