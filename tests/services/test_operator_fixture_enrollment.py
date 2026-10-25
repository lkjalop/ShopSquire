import uuid

import pytest
from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.operator_tenant_membership import principal_hash_for_api_key


@pytest.mark.parametrize(
    "environment,enroll_only,expected",
    [
        ("testing", True, "enrolled"),
        ("production", True, "rejected"),
        ("testing", False, "missing_product"),
    ],
)
def test_fixture_enrollment_is_explicit_and_does_not_need_or_seed_stock(
    monkeypatch, environment, enroll_only, expected
):
    from scripts.seed_operator_inventory_demo import main

    marker = uuid.uuid4().hex
    tenant = "default" if enroll_only else "synthetic-" + marker
    monkeypatch.setenv("APP_ENV", environment)
    keys = {role: f"enrollment-{role}-{marker}" for role in ["owner", "merchant", "developer"]}
    for role, key in keys.items():
        monkeypatch.setenv(role.upper() + "_API_KEY", key)
    arguments = ["seed_operator_inventory_demo", "--tenant", tenant, "--sku", "missing-" + marker]
    if enroll_only:
        arguments.append("--enroll-only")
    monkeypatch.setattr("sys.argv", arguments)
    if expected == "rejected":
        with pytest.raises(SystemExit):
            main()
    elif expected == "missing_product":
        with pytest.raises(ValueError, match="existing_sku_required"):
            main()
    else:
        main()
    with db_session() as db:
        for role, key in keys.items():
            row = db.execute(
                text(
                    "SELECT role,status FROM operator_tenant_membership "
                    "WHERE tenant_id=:tenant AND principal_hash=:principal"
                ),
                {"tenant": tenant, "principal": principal_hash_for_api_key(key)},
            ).first()
            assert (tuple(row) if row else None) == (
                (role, "active") if expected == "enrolled" else None
            )
        assert (
            db.scalar(
                text("SELECT COUNT(*) FROM inventory_level WHERE tenant_id=:tenant AND sku=:sku"),
                {"tenant": tenant, "sku": "missing-" + marker},
            )
            == 0
        )
