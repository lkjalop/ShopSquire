from __future__ import annotations

from typing import Optional
from sqlalchemy import text

from src.app.models.db import db_session


def get_expected_serial(order_id: Optional[str]) -> Optional[str]:
    """Return expected serial for an order if available.
    Checks orders.serial_number if the column exists, otherwise looks up order_serials(order_id, serial).
    """
    if not order_id:
        return None
    try:
        with db_session() as db:
            # Check if orders has serial_number column
            try:
                cols = db.execute(text("PRAGMA table_info(orders)")).fetchall()
                has_col = any((c[1] == "serial_number") for c in cols)
            except Exception:
                has_col = False
            if has_col:
                row = db.execute(text("SELECT serial_number FROM orders WHERE id = :id"), {"id": order_id}).fetchone()
                if row and row[0]:
                    return str(row[0])
            # Fallback to order_serials mapping table
            try:
                row2 = db.execute(text("SELECT serial FROM order_serials WHERE order_id = :id"), {"id": order_id}).fetchone()
                if row2 and row2[0]:
                    return str(row2[0])
            except Exception:
                return None
    except Exception:
        return None
    return None
