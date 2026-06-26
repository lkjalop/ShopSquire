"""Seed the demo supplier catalog so the procurement happy-path runs end-to-end.

Creates suppliers + supplier_products + trusted_supplier_domains rows so the DEFAULT draft path resolves
an approved supplier (instead of NO_APPROVED_SUPPLIER). Idempotent — safe to re-run.

Usage:  PYTHONPATH=. python scripts/seed_suppliers.py
"""
from __future__ import annotations

from src.app.models.db import db_session
from src.app.services.supplier_catalog import DEMO_SKUS, seed_demo


def main() -> None:
    with db_session() as db:
        counts = seed_demo(db, skus=DEMO_SKUS)
    print(f"seeded suppliers={counts.get('suppliers')} products={counts.get('products')} "
          f"domains={counts.get('domains')} for skus={DEMO_SKUS}")


if __name__ == "__main__":
    main()
