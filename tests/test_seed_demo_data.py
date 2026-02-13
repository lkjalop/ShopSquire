import pathlib

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from scripts.seed_demo_data import seed_customers, seed_decisions, seed_orders, seed_products, seed_security_events


def _apply_schema(engine):
    schema_path = pathlib.Path("db/schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with engine.connect() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
        conn.commit()


def test_seed_demo_data():
    engine = create_engine("sqlite:///:memory:", future=True)
    _apply_schema(engine)
    Session = sessionmaker(bind=engine, future=True)
    with Session() as db:
        seed_customers(db)
        seed_products(db)
        seed_orders(db)
        seed_decisions(db)
        seed_security_events(db)
        db.commit()

        customers = db.execute(text("SELECT COUNT(*) FROM customers")).scalar()
        products = db.execute(text("SELECT COUNT(*) FROM products")).scalar()
        orders = db.execute(text("SELECT COUNT(*) FROM orders")).scalar()
        decisions = db.execute(text("SELECT COUNT(*) FROM decision_logs")).scalar()
        events = db.execute(text("SELECT COUNT(*) FROM security_events")).scalar()

        assert customers and customers > 0
        assert products and products > 0
        assert orders and orders > 0
        assert decisions and decisions > 0
        assert events and events > 0
