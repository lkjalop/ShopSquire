from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import List

# Ensure repo root is importable when running as a script (sys.path[0] becomes
# `scripts/` which otherwise hides `/app/src` in Docker).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.app.erp.connectors.csv_inventory import CSVInventoryConnector
from src.app.erp.connectors.shopify_inventory import ShopifyInventoryConnector
from src.app.erp.sync import sync_inventory


def _connectors_from_env() -> List[str]:
    raw = os.getenv("INVENTORY_SYNC_CONNECTORS", "csv").strip()
    ids = [s.strip().lower() for s in raw.split(",") if s.strip()]
    return ids or ["csv"]


def _interval_sec() -> int:
    try:
        return max(30, min(24 * 3600, int(float(os.getenv("INVENTORY_SYNC_INTERVAL_SEC", "300") or 300))))
    except Exception:
        return 300


def _bool_env(key: str, default: bool) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _make(connector_id: str):
    if connector_id == "csv":
        return CSVInventoryConnector()
    if connector_id == "shopify":
        return ShopifyInventoryConnector()
    return None


def main() -> int:
    tenant_id = os.getenv("TENANT_ID") or None
    dry_run = _bool_env("INVENTORY_SYNC_DRY_RUN", False)
    upsert_products = _bool_env("INVENTORY_SYNC_UPSERT_PRODUCTS", False)
    interval = _interval_sec()
    connectors = _connectors_from_env()

    # Allow API to run migrations / DB to start first.
    try:
        time.sleep(int(float(os.getenv("INVENTORY_SYNC_STARTUP_DELAY_SEC", "10") or 10)))
    except Exception:
        time.sleep(10)

    while True:
        for cid in connectors:
            c = _make(cid)
            if c is None:
                print({"connector": cid, "status": "skipped", "error": "unknown_connector"})
                continue
            h = c.health()
            if not h.get("ok"):
                print({"connector": cid, "status": "skipped", "error": "unhealthy", "health": h})
                continue
            try:
                out = sync_inventory(connector=c, tenant_id=tenant_id, dry_run=dry_run, upsert_products=upsert_products)
                print({"connector": cid, **out})
            except Exception as exc:
                print({"connector": cid, "status": "failed", "error": str(exc)})
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
