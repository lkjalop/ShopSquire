"""Seed the demo supplier catalog so the procurement happy-path runs end-to-end.

Creates suppliers + supplier_products + trusted_supplier_domains rows so the DEFAULT draft path resolves
an approved supplier (instead of NO_APPROVED_SUPPLIER), plus the canonical price_book_entry +
inventory_level rows (retail + stock) so the deal-economics JOIN has data. Idempotent — safe to re-run.

Usage:  PYTHONPATH=. python scripts/seed_suppliers.py
"""
from __future__ import annotations

from src.app.models.db import db_session
from src.app.services import commerce_catalog, competitor_source, funnel_source, support_objection_source
from src.app.services.supplier_catalog import DEMO_SKUS, seed_demo, seed_demo_vendor_contacts


def main() -> None:
    with db_session() as db:
        counts = seed_demo(db, skus=DEMO_SKUS)
        cat = commerce_catalog.seed_demo(db)
        comp = competitor_source.seed_demo(db)
        obj = support_objection_source.seed_demo(db)
        fun = funnel_source.seed_demo(db)
    vendors = seed_demo_vendor_contacts()  # kyv_vendors manage their own session
    print(f"seeded suppliers={counts.get('suppliers')} products={counts.get('products')} "
          f"domains={counts.get('domains')} for skus={DEMO_SKUS}")
    print(f"seeded catalog prices={cat.get('prices')} inventory={cat.get('inventory')}")
    print(f"seeded competitor observations={comp.get('observations')} "
          f"support objections={obj.get('observations')} funnel events={fun.get('events')}")
    print(f"seeded verified vendor contacts={vendors}")


if __name__ == "__main__":
    main()
