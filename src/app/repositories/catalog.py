from typing import Optional, Dict, List
from sqlalchemy import select, or_, func

from src.app.models.db import db_session
from src.app.models.orm import Product, Inventory, DraftOrder


class CatalogRepository:
    def __init__(self, session=None):
        # Optional injected SQLAlchemy Session (bound to request engine); when provided,
        # repository reads/writes will use this session instead of the module-level db_session.
        self._session = session

    def _get_session(self):
        if self._session is not None:
            return self._session
        # Fall back to module-level session when no injected session provided
        return None

    def get_product_by_sku(self, sku: str) -> Optional[Product]:
        sess = self._get_session()
        if sess is not None:
            try:
                res = sess.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()
                return res
            except Exception:
                pass
        with db_session() as db:
            res = db.execute(select(Product).where(Product.sku == sku)).scalar_one_or_none()
            return res

    def get_stock_by_product_id(self, product_id: str) -> Optional[int]:
        sess = self._get_session()
        if sess is not None:
            try:
                res = sess.execute(select(Inventory).where(Inventory.product_id == product_id)).scalar_one_or_none()
                return res.stock if res else None
            except Exception:
                pass
        with db_session() as db:
            res = db.execute(select(Inventory).where(Inventory.product_id == product_id)).scalar_one_or_none()
            return res.stock if res else None

    def get_stock_by_product_ids(self, product_ids: list) -> Dict[str, int]:
        """Fetch stock for a list of product ids in a single query.

        Returns a mapping of product_id -> stock (int). Missing ids are omitted.
        """
        if not product_ids:
            return {}
        sess = self._get_session()
        try:
            if sess is not None:
                rows = sess.execute(select(Inventory).where(Inventory.product_id.in_(product_ids))).scalars().all()
                return {r.product_id: r.stock for r in rows if r}
        except Exception:
            pass
        with db_session() as db:
            rows = db.execute(select(Inventory).where(Inventory.product_id.in_(product_ids))).scalars().all()
            return {r.product_id: r.stock for r in rows if r}

    def get_products_by_ids(self, product_ids: list[str]) -> List[Product]:
        """Fetch products by a list of ids (best-effort).

        Returns a list of Product objects in unspecified order.
        """
        if not product_ids:
            return []
        sess = self._get_session()
        try:
            if sess is not None:
                res = sess.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()
                return list(res)
        except Exception:
            pass
        with db_session() as db:
            res = db.execute(select(Product).where(Product.id.in_(product_ids))).scalars().all()
            return list(res)

    def get_draft_order(self, draft_order_id: str) -> Optional[DraftOrder]:
        sess = self._get_session()
        if sess is not None:
            try:
                return sess.execute(select(DraftOrder).where(DraftOrder.id == draft_order_id)).scalar_one_or_none()
            except Exception:
                pass
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

    def search_products(
        self,
        query: str,
        limit: int = 10,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        sort_by: str = "relevance"
    ) -> List[Product]:
        """Search products with optional price filtering and sorting.

        Args:
            query: Search keywords
            limit: Max results to return
            min_price: Minimum price in dollars (converted to cents internally)
            max_price: Maximum price in dollars (converted to cents internally)
            sort_by: 'price_asc', 'price_desc', or 'relevance'
        """
        if not query:
            return []
        tokens = [t.strip().lower() for t in query.replace(",", " ").split() if len(t.strip()) > 2]
        expanded = set(tokens)
        for t in list(tokens):
            if t.endswith("s") and len(t) > 3:
                expanded.add(t[:-1])

        # Build base query - for generic category return broad list
        if any(cat in expanded for cat in ("laptop", "laptops")):
            base_query = select(Product)
        elif not expanded:
            return []
        else:
            clauses = []
            for tok in expanded:
                like = f"%{tok}%"
                clauses.append(func.lower(Product.name).like(like))
                clauses.append(func.lower(Product.sku).like(like))
            base_query = select(Product).where(or_(*clauses))

        # Apply price filtering at database level
        if min_price is not None:
            base_query = base_query.where(Product.price_cents >= min_price * 100)
        if max_price is not None:
            base_query = base_query.where(Product.price_cents <= max_price * 100)

        # Apply sorting
        if sort_by == "price_asc":
            base_query = base_query.order_by(Product.price_cents.asc())
        elif sort_by == "price_desc":
            base_query = base_query.order_by(Product.price_cents.desc())
        # else: relevance (default order)

        base_query = base_query.limit(limit)

        sess = self._get_session()
        if sess is not None:
            try:
                res = sess.execute(base_query).scalars().all()
                return list(res)
            except Exception:
                pass
        with db_session() as db:
            res = db.execute(base_query).scalars().all()
            return list(res)

    def list_products(
        self,
        limit: int = 200,
        min_price: Optional[int] = None,
        max_price: Optional[int] = None,
        sort_by: str = "price_asc"
    ) -> List[Product]:
        """List products with optional price filtering and sorting.

        Default sort is by price ascending (cheapest first).
        """
        base_query = select(Product)

        # Apply price filtering
        if min_price is not None:
            base_query = base_query.where(Product.price_cents >= min_price * 100)
        if max_price is not None:
            base_query = base_query.where(Product.price_cents <= max_price * 100)

        # Apply sorting - default to price ascending
        if sort_by == "price_desc":
            base_query = base_query.order_by(Product.price_cents.desc())
        else:
            base_query = base_query.order_by(Product.price_cents.asc())

        base_query = base_query.limit(limit)

        sess = self._get_session()
        if sess is not None:
            try:
                res = sess.execute(base_query).scalars().all()
                return list(res)
            except Exception:
                pass
        with db_session() as db:
            res = db.execute(base_query).scalars().all()
            return list(res)
