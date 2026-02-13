from __future__ import annotations

import csv
import os
from typing import Any, Dict, List

from src.app.erp.connectors.base import InventoryConnector, InventoryRecord


class CSVInventoryConnector:
    """Read-only connector for CSV inventory dumps.

    Expected columns (case-insensitive):
      - sku (required)
      - stock (required)
      - warehouse (optional, default "default")
      - updated_at (optional)

    Configure with env var `CSV_INVENTORY_PATH` or pass a path.
    """

    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("CSV_INVENTORY_PATH") or ""

    def name(self) -> str:
        return "csv"

    def health(self) -> Dict[str, Any]:
        if not self.path:
            return {"ok": False, "error": "CSV_INVENTORY_PATH not set"}
        if not os.path.exists(self.path):
            return {"ok": False, "error": f"missing file: {self.path}"}
        return {"ok": True, "path": self.path}

    def fetch_inventory(self, *, tenant_id: str | None = None) -> List[InventoryRecord]:
        if not self.path or not os.path.exists(self.path):
            return []
        out: List[InventoryRecord] = []
        with open(self.path, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if not isinstance(row, dict):
                    continue
                # Normalize keys
                norm = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
                sku = str(norm.get("sku") or "").strip()
                if not sku:
                    continue
                wh = str(norm.get("warehouse") or "default").strip() or "default"
                try:
                    stock = int(float(norm.get("stock") or 0))
                except Exception:
                    stock = 0
                updated_at = str(norm.get("updated_at") or "") or None
                out.append(InventoryRecord(sku=sku, warehouse=wh, stock=stock, updated_at=updated_at, source=self.name()))
        return out


def create_connector() -> InventoryConnector:
    return CSVInventoryConnector()

