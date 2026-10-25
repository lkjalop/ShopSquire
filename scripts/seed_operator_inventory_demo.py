"""Enroll fictional operators from server credentials and seed untouched demo stock."""

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="synthetic-inventory-ops")
    parser.add_argument("--sku", default="LAP-01B48B57")
    parser.add_argument("--enroll-only", action="store_true")
    args = parser.parse_args()
    if os.getenv("APP_ENV") not in ("local", "test", "testing") or not (
        args.tenant.startswith("synthetic-") or (args.tenant == "default" and args.enroll_only)
    ):
        parser.error("Local/test synthetic tenant required")
    from sqlalchemy import text
    from src.app.models.db import db_session
    from src.app.security.auth import _role_keys
    from src.app.services.operator_tenant_membership import (
        principal_hash_for_api_key,
        grant_membership,
    )
    from src.app.services.fulfillment.person_approval import bind_person
    from src.app.services.electronics_shop_scenario import seed_scenario

    keys = _role_keys()
    with db_session() as db:
        if not args.enroll_only:
            product = db.execute(
                text("SELECT price_cents FROM products WHERE sku=:sku"), {"sku": args.sku}
            ).first()
            if not product:
                raise ValueError("existing_sku_required")
            existing = db.execute(
                text("SELECT 1 FROM synthetic_shop_history WHERE tenant_id=:tenant AND sku=:sku"),
                dict(tenant=args.tenant, sku=args.sku),
            ).first()
            if not existing:
                seed_scenario(db, tenant_id=args.tenant, sku=args.sku, retail_cents=product[0])
        for role, person in [
            ("merchant", "fixture-requester"),
            ("developer", "fixture-requester"),
            ("owner", "fixture-approver"),
        ]:
            principal = principal_hash_for_api_key(keys[role])
            membership = db.execute(
                text(
                    "SELECT role,status FROM operator_tenant_membership WHERE tenant_id=:tenant AND principal_hash=:principal"
                ),
                dict(tenant=args.tenant, principal=principal),
            ).first()
            if membership and (membership[0] != role or membership[1] != "active"):
                raise ValueError("existing_membership_requires_explicit_review")
            if not membership:
                grant_membership(
                    db,
                    principal_hash=principal,
                    tenant_id=args.tenant,
                    role=role,
                    subject_id=person,
                    auth_method="api_key",
                    created_by="local-fixture-enrollment",
                )
            bind_person(
                db,
                tenant_id=args.tenant,
                principal_hash=principal,
                person_id=person,
                assigned_by="local-fixture-enrollment",
            )
        db.commit()
    print("Synthetic operators enrolled; existing stock was preserved.")


if __name__ == "__main__":
    main()
