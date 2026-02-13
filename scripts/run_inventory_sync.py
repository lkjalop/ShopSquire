from __future__ import annotations

import argparse
import os
from typing import Any, Dict

from src.app.erp.sync import sync_inventory
from src.app.erp.connectors.csv_inventory import CSVInventoryConnector
from src.app.erp.connectors.shopify_inventory import ShopifyInventoryConnector


def _connector(connector_id: str, *, csv_path: str | None = None):
    cid = (connector_id or "csv").strip().lower()
    if cid == "csv":
        return CSVInventoryConnector(path=csv_path)
    if cid == "shopify":
        return ShopifyInventoryConnector()
    raise SystemExit(f"Unsupported connector: {connector_id}")


def main() -> int:
    p = argparse.ArgumentParser(description="ShopSquire inventory sync (Phase 5 MVP)")
    p.add_argument("--connector", default="csv", choices=["csv", "shopify"])
    p.add_argument("--tenant-id", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--upsert-products", action="store_true")
    p.add_argument("--csv-path", default=None, help="Overrides CSV_INVENTORY_PATH for the csv connector")
    args = p.parse_args()

    c = _connector(args.connector, csv_path=args.csv_path)
    h = c.health()
    if not h.get("ok"):
        print(f"Connector unhealthy: {h}")
        return 2

    out: Dict[str, Any] = sync_inventory(
        connector=c,
        tenant_id=args.tenant_id,
        dry_run=bool(args.dry_run),
        upsert_products=bool(args.upsert_products),
    )
    print(out)
    return 0 if out.get("status") != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

