"""Demo seed for sales_metrics — powers /margin-intelligence, velocity/DSI and demand-trend.

DEMO DATA (clearly labeled): the catalog carries no per-SKU wholesale cost and orders carry no
line-item SKU, so we synthesize a plausible, DETERMINISTIC sales history per active product:
  • revenue_cents = real catalog price_cents x units
  • cost_cents    = revenue x (1 - margin), margin deterministic per SKU in [0.16, 0.30]
  • velocity tier (fast / medium / slow-'surplus') deterministic per SKU, so DSI + surplus vary
  • a mild recent uptrend on fast movers so demand-trend shows a real spike

Idempotent: rows are keyed 'seed:<sku>:<day>' and replaced on re-run. Real order flow (or the
synthetic_reco_lab interaction seeder) would supersede this once live signals exist.

Run:  python scripts/seed_demo_sales_metrics.py [db_path]
"""
from __future__ import annotations

import hashlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DB = sys.argv[1] if len(sys.argv) > 1 else "C:/AI/ShopSquire/tmp/demo.sqlite"
WINDOW_DAYS = 90


def _h(s: str) -> int:
    return int(hashlib.sha256(s.encode()).hexdigest(), 16)


def _units(sku: str, day: int, tier: int) -> int:
    d = _h(f"{sku}:{day}")
    if tier == 0:          # fast mover
        base = 1 + d % 5
        return base + (2 if day < 14 else 0)   # recent uptrend -> demand spike
    if tier == 1:          # medium
        return d % 2
    return 1 if d % 18 == 0 else 0             # slow / surplus candidate


def main() -> None:
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS sales_metrics (
               id TEXT PRIMARY KEY, sku TEXT NOT NULL, quantity INTEGER DEFAULT 1,
               revenue_cents INTEGER DEFAULT 0, cost_cents INTEGER DEFAULT 0,
               event_time TEXT DEFAULT CURRENT_TIMESTAMP)"""
    )
    cur.execute("DELETE FROM sales_metrics WHERE id LIKE 'seed:%'")
    products = cur.execute(
        "SELECT sku, COALESCE(price_cents,0) FROM products WHERE active=1 AND COALESCE(price_cents,0) > 0"
    ).fetchall()
    now = datetime.now(timezone.utc)
    rows, total_units = [], 0
    for sku, price in products:
        margin = 0.16 + (_h(sku) % 15) / 100.0        # 0.16..0.30, stable per SKU
        tier = _h(sku) % 3                             # 0 fast, 1 medium, 2 slow/surplus
        for day in range(WINDOW_DAYS):
            u = _units(sku, day, tier)
            if u <= 0:
                continue
            revenue = int(price) * u
            cost = int(round(revenue * (1.0 - margin)))
            ts = (now - timedelta(days=day)).isoformat()
            rows.append((f"seed:{sku}:{day}", sku, u, revenue, cost, ts))
            total_units += u
    cur.executemany(
        "INSERT OR REPLACE INTO sales_metrics (id, sku, quantity, revenue_cents, cost_cents, event_time)"
        " VALUES (?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    n = cur.execute("SELECT COUNT(*) FROM sales_metrics").fetchone()[0]
    skus = cur.execute("SELECT COUNT(DISTINCT sku) FROM sales_metrics").fetchone()[0]
    print(f"seeded sales_metrics: {len(rows)} rows ({total_units} units) across {skus} SKUs; table now {n} rows")
    con.close()


if __name__ == "__main__":
    main()
