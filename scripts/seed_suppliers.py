"""Seed the demo supplier catalog so the procurement happy-path runs end-to-end.

Creates suppliers + supplier_products + trusted_supplier_domains rows so the DEFAULT draft path resolves
an approved supplier (instead of NO_APPROVED_SUPPLIER), plus the canonical price_book_entry +
inventory_level rows (retail + stock) so the deal-economics JOIN has data. Idempotent — safe to re-run.

Usage:  PYTHONPATH=. python scripts/seed_suppliers.py
"""
from __future__ import annotations

from src.app.models.db import db_session
from src.app.services import commerce_catalog, competitor_source, funnel_source, support_objection_source
from src.app.services.supplier_catalog import (
    ensure_supplier_coverage,
    seed_demo_supplier_history,
    seed_demo_vendor_contacts,
)


def main() -> None:
    with db_session() as db:
        # Coverage follows the catalog: every active SKU the recommender can surface (GAM-*/LAP-*) gets an
        # approved supplier, so the procurement draft path never dead-ends at NO_APPROVED_SUPPLIER.
        counts = ensure_supplier_coverage(db)
        cat = commerce_catalog.seed_demo(db)
        # per-(sku, location) stock so the multi-location / transfer alternative has real data to surface.
        loc_rows = commerce_catalog.seed_demo_locations(db)
        comp = competitor_source.seed_demo(db)
        obj = support_objection_source.seed_demo(db)
        fun = funnel_source.seed_demo(db)
    vendors = seed_demo_vendor_contacts()  # kyv_vendors manage their own session
    history = seed_demo_supplier_history()  # supplier_baseline_events — prior-dealings context
    print(f"seeded suppliers={counts.get('suppliers')} products={counts.get('products')} "
          f"domains={counts.get('domains')} (coverage tracks the live catalog)")
    print(f"seeded supplier history events={history}")
    print(f"seeded catalog prices={cat.get('prices')} inventory={cat.get('inventory')} "
          f"per-location rows={loc_rows}")
    print(f"seeded competitor observations={comp.get('observations')} "
          f"support objections={obj.get('observations')} funnel events={fun.get('events')}")
    print(f"seeded verified vendor contacts={vendors}")


if __name__ == "__main__":
    main()
