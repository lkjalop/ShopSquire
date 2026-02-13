from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text

from src.app.erp.connectors.base import InventoryConnector, InventoryRecord
from src.app.models.db import db_session


class SQLiteCatalogConnector:
    """Read-only connector that uses ShopSquire's local `products`+`inventory` tables.

    Useful for demo/local deployments and as a reference implementation for real
    ERP/WMS connectors.
    """

    def name(self) -> str:
        return "sqlite_catalog"

    def health(self) -> Dict[str, Any]:
        try:
            with db_session() as db:
                db.execute(text("SELECT 1"))
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def fetch_inventory(self, *, tenant_id: str | None = None) -> List[InventoryRecord]:
        out: List[InventoryRecord] = []
        with db_session() as db:
            rows = db.execute(
                text(
                    """
                    SELECT p.sku, COALESCE(i.warehouse, 'default') as warehouse, COALESCE(i.stock, 0) as stock, i.updated_at
                    FROM inventory i
                    JOIN products p ON p.id = i.product_id
                    """
                )
            ).fetchall()
            for r in rows or []:
                out.append(
                    InventoryRecord(
                        sku=str(r[0]),
                        warehouse=str(r[1] or "default"),
                        stock=int(r[2] or 0),
                        updated_at=str(r[3]) if r[3] is not None else None,
                        source=self.name(),
                    )
                )
        return out


def create_connector() -> InventoryConnector:
    return SQLiteCatalogConnector()

