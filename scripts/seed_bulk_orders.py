#!/usr/bin/env python3
"""
Seed a large order history for dashboard/backfill testing.

This is intentionally deterministic-ish and lightweight: it only populates `orders`
and `order_sessions` (plus seeds customers/products if missing).

Examples (host -> Docker Postgres):
  set DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire
  python scripts/seed_bulk_orders.py --count 750 --uid demo-user-1
"""

from __future__ import annotations

import argparse
import json
import os
import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.models.db import db_session


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.utcnow()


def _ensure_basics(db) -> None:
    # Seed minimal demo entities if empty.
    try:
        customers = int(db.execute(text("SELECT COUNT(*) FROM customers")).scalar() or 0)
    except Exception:
        customers = 0
    try:
        products = int(db.execute(text("SELECT COUNT(*) FROM products")).scalar() or 0)
    except Exception:
        products = 0
    if customers > 0 and products > 0:
        return
    try:
        from scripts.seed_demo_data import seed_customers, seed_products  # type: ignore

        seed_customers(db)
        seed_products(db)
    except Exception:
        pass


def seed_orders(*, count: int, uid: str, days: int, seed: int) -> dict:
    rng = random.Random(int(seed))
    with db_session() as db:
        _ensure_basics(db)
        cust = db.execute(text("SELECT id FROM customers ORDER BY created_at DESC LIMIT 1")).fetchone()
        if not cust:
            return {"ok": False, "error": "no_customer"}
        cid = cust[0]

        existing = int(db.execute(text("SELECT COUNT(*) FROM orders")).scalar() or 0)
        created = 0
        statuses = ["paid", "paid", "paid", "refunded", "chargeback", "pending_payment"]
        currencies = ["USD", "USD", "USD", "AUD"]

        for _ in range(int(count)):
            order_id = _uuid()
            # Spread over last N days with a slight clustering.
            age_days = int(rng.triangular(0, max(1, int(days)), max(1, int(days) * 0.35)))
            created_at = _utcnow() - timedelta(days=age_days, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
            total = int(rng.triangular(4500, 320000, 129900))  # cents
            status = rng.choice(statuses)
            currency = rng.choice(currencies)

            db.execute(
                text(
                    "INSERT INTO orders (id, customer_id, total_cents, currency, status, created_at, updated_at) "
                    "VALUES (:id, :customer_id, :total_cents, :currency, :status, :created_at, :updated_at)"
                ),
                {
                    "id": order_id,
                    "customer_id": cid,
                    "total_cents": total,
                    "currency": currency,
                    "status": status,
                    "created_at": created_at.isoformat(),
                    "updated_at": created_at.isoformat(),
                },
            )
            db.execute(
                text("INSERT INTO order_sessions (id, uid, order_id, created_at) VALUES (:id, :uid, :order_id, :created_at)"),
                {"id": _uuid(), "uid": uid, "order_id": order_id, "created_at": created_at.isoformat()},
            )
            created += 1

        db.commit()
        final = int(db.execute(text("SELECT COUNT(*) FROM orders")).scalar() or 0)
        # Basic stats for quick sanity
        stats = db.execute(
            text(
                "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY COUNT(*) DESC"
            )
        ).fetchall()
        return {
            "ok": True,
            "existing_before": existing,
            "created": created,
            "final_orders": final,
            "status_counts": {str(r[0]): int(r[1]) for r in (stats or [])},
            "uid": uid,
            "days": days,
            "seed": seed,
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=700)
    ap.add_argument("--uid", type=str, default="demo-user-1")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=1337)
    args = ap.parse_args()

    if args.count <= 0:
        raise SystemExit("--count must be > 0")
    out = seed_orders(count=args.count, uid=args.uid, days=args.days, seed=args.seed)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
