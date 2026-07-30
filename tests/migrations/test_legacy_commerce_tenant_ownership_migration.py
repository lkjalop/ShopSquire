import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migration():
    path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260831_legacy_commerce_tenant_ownership.py"
    )
    spec = importlib.util.spec_from_file_location("legacy_commerce_tenant_ownership", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_legacy_commerce_ownership_is_derived_only_from_tenant_scoped_orders():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE customers (id TEXT PRIMARY KEY)"))
        connection.execute(
            sa.text(
                "CREATE TABLE draft_orders "
                "(id TEXT PRIMARY KEY, customer_id TEXT, tenant_id TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE orders "
                "(id TEXT PRIMARY KEY, draft_order_id TEXT, customer_id TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE order_sessions "
                "(id TEXT PRIMARY KEY, uid TEXT NOT NULL, order_id TEXT NOT NULL)"
            )
        )
        connection.execute(sa.text("INSERT INTO customers (id) VALUES ('buyer-a'), ('buyer-b')"))
        connection.execute(
            sa.text(
                "INSERT INTO draft_orders (id, customer_id, tenant_id) VALUES "
                "('draft-a', 'buyer-a', 'tenant-a'), "
                "('draft-b1', 'buyer-b', 'tenant-a'), "
                "('draft-b2', 'buyer-b', 'tenant-b')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO orders (id, draft_order_id, customer_id) VALUES "
                "('order-a', 'draft-a', 'buyer-a'), "
                "('order-b1', 'draft-b1', 'buyer-b'), "
                "('order-b2', 'draft-b2', 'buyer-b')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO order_sessions (id, uid, order_id) VALUES "
                "('session-a', 'buyer-a', 'order-a'), "
                "('session-b1', 'buyer-b', 'order-b1')"
            )
        )

        module = _migration()
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        module.upgrade()

        assert connection.execute(
            sa.text("SELECT tenant_id FROM orders WHERE id='order-a'")
        ).scalar_one() == "tenant-a"
        assert connection.execute(
            sa.text("SELECT tenant_id FROM order_sessions WHERE id='session-a'")
        ).scalar_one() == "tenant-a"
        assert connection.execute(
            sa.text("SELECT tenant_id FROM customers WHERE id='buyer-a'")
        ).scalar_one() == "tenant-a"

        # A customer observed across multiple tenants is deliberately left
        # unclassified; migration must never choose one tenant arbitrarily.
        ambiguous = connection.execute(
            sa.text(
                "SELECT tenant_id, tenant_ownership_status "
                "FROM customers WHERE id='buyer-b'"
            )
        ).one()
        assert ambiguous == (None, "unclassified")


def test_new_ownership_columns_and_indexes_are_present():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE customers (id TEXT PRIMARY KEY)"))
        connection.execute(
            sa.text("CREATE TABLE orders (id TEXT PRIMARY KEY, customer_id TEXT)")
        )
        connection.execute(
            sa.text(
                "CREATE TABLE order_sessions "
                "(id TEXT PRIMARY KEY, uid TEXT NOT NULL, order_id TEXT NOT NULL)"
            )
        )
        module = _migration()
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()

    inspector = sa.inspect(engine)
    for table in ("customers", "orders", "order_sessions"):
        columns = {column["name"]: column for column in inspector.get_columns(table)}
        assert columns["tenant_id"]["nullable"] is True
        assert columns["tenant_ownership_status"]["nullable"] is False
        assert any(
            index["column_names"][0] == "tenant_id"
            for index in inspector.get_indexes(table)
        )
