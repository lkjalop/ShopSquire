import sqlalchemy as sa
from sqlalchemy.orm import Session

from src.app.services.legacy_commerce_tenant_ownership import (
    erase_authoritatively_owned_subject_rows,
)


def test_erasure_is_tenant_scoped_and_reports_unclassified_rows():
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE customers "
                "(id TEXT, tenant_id TEXT, tenant_ownership_status TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE orders "
                "(id TEXT, customer_id TEXT, tenant_id TEXT, tenant_ownership_status TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE order_sessions "
                "(id TEXT, uid TEXT, order_id TEXT, tenant_id TEXT, tenant_ownership_status TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO customers VALUES "
                "('buyer', 'tenant-a', 'authenticated_request_context'), "
                "('buyer', 'tenant-b', 'authenticated_request_context'), "
                "('buyer', NULL, 'unclassified')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO orders VALUES "
                "('a', 'buyer', 'tenant-a', 'derived_from_tenant_draft'), "
                "('b', 'buyer', 'tenant-b', 'derived_from_tenant_draft'), "
                "('u', 'buyer', NULL, 'unclassified')"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO order_sessions VALUES "
                "('sa', 'buyer', 'a', 'tenant-a', 'derived_from_tenant_order'), "
                "('sb', 'buyer', 'b', 'tenant-b', 'derived_from_tenant_order'), "
                "('su', 'buyer', 'u', NULL, 'unclassified')"
            )
        )

    with Session(engine) as session:
        result = erase_authoritatively_owned_subject_rows(
            session, tenant_id="tenant-a", uid="buyer"
        )
        session.commit()

    assert result["deleted"] == {
        "order_sessions": 1,
        "orders": 1,
        "customers": 1,
    }
    assert result["unclassified"] == {
        "order_sessions": 1,
        "orders": 1,
        "customers": 1,
    }
    with engine.connect() as connection:
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM orders WHERE tenant_id='tenant-b'")
        ).scalar_one() == 1
        assert connection.execute(
            sa.text("SELECT COUNT(*) FROM orders WHERE tenant_id IS NULL")
        ).scalar_one() == 1
