"""Apply explicit, source-backed catalog corrections and rebuild demo offers."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services import commerce_catalog
from src.app.services.supplier_catalog import seed_demo_supplier_offers


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", default="config/catalog_corrections_au.json")
    args = parser.parse_args()
    path = Path(args.file)
    payload = json.loads(path.read_text(encoding="utf-8"))
    tenant = str(payload.get("tenant_id") or "").strip()
    currency = str(payload.get("currency") or "").strip().upper()
    if not tenant or len(currency) != 3:
        raise ValueError("correction file requires tenant_id and ISO currency")
    changed = missing = 0
    corrected_skus = []
    with db_session() as db:
        for item in payload.get("corrections") or []:
            sku, cents = str(item.get("sku") or "").strip(), int(item.get("price_cents") or 0)
            row = db.execute(text("SELECT 1 FROM products WHERE sku=:sku"), {"sku": sku}).fetchone()
            if not row:
                missing += 1
                continue
            db.execute(text(
                "UPDATE products SET price_cents=:cents, currency=:currency, "
                "updated_at=CURRENT_TIMESTAMP WHERE sku=:sku"
            ), {"cents": cents, "currency": currency, "sku": sku})
            commerce_catalog.upsert_price(
                db, sku=sku, list_cents=cents, currency=currency,
                source=f"catalog_correction:{path.name}", tenant_id=tenant,
            )
            # Demo estimates are derived from source retail. Replace only simulation rows;
            # validated supplier offers and quotes are never touched by a catalog correction.
            db.execute(text(
                "DELETE FROM supplier_offer WHERE tenant_id=:tenant AND sku=:sku "
                "AND simulation_only=1"
            ), {"tenant": tenant, "sku": sku})
            corrected_skus.append(sku)
            changed += 1
        db.commit()
        seeded = seed_demo_supplier_offers(db, tenant_id=tenant)
    print(json.dumps({"file": str(path), "tenant_id": tenant, "currency": currency,
                      "changed": changed, "missing": missing, "corrected_skus": corrected_skus,
                      "demo_offers_seeded": seeded.get("offers")}, indent=2))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
