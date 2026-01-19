from typing import Optional, Dict
from sqlalchemy import select

from src.app.models.db import db_session
from src.app.models.orm import Product, Inventory, DraftOrder


class CatalogRepository:
    def get_product_by_sku(self, sku: str) -> Optional[Product]:
        with db_session() as db:
            res = db.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()
            return res

    def get_stock_by_product_id(self, product_id: str) -> Optional[int]:
        with db_session() as db:
            res = db.execute(select(Inventory).where(Inventory.product_id == product_id)).scalar_one_or_none()
            return res.stock if res else None

    def get_draft_order(self, draft_order_id: str) -> Optional[DraftOrder]:
        with db_session() as db:
            return db.execute(select(DraftOrder).where(DraftOrder.id == draft_order_id)).scalar_one_or_none()

    def compute_cart_total(self, draft_order_id: str) -> Optional[int]:
        order = self.get_draft_order(draft_order_id)
        if not order:
            return None
        total = 0
        items: list[Dict] = order.line_items or []
        for it in items:
            sku = it.get("sku")
            qty = int(it.get("quantity", 1))
            product = self.get_product_by_sku(sku) if sku else None
            if product:
                total += product.price_cents * qty
        return total
