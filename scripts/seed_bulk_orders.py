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
from typing import Any, Dict, List, Tuple

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.models.db import db_session


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.utcnow()


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        # Accept YYYY-MM-DD
        return datetime.strptime(s, "%Y-%m-%d")
    except Exception:
        pass
    try:
        # Accept ISO-ish string
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _rand_dt_between(rng: random.Random, start: datetime, end: datetime) -> datetime:
    # Triangular clustering towards more recent dates, but bounded.
    span = max(1.0, (end - start).total_seconds())
    mode = span * 0.65
    sec = float(rng.triangular(0.0, span, mode))
    return start + timedelta(seconds=sec)


def _bucket_ranges() -> List[Tuple[str, int, int]]:
    # Name, min_cents (inclusive), max_cents (exclusive)
    return [
        ("lt_100", 1_00, 10_000),
        ("lt_500", 10_000, 50_000),
        ("lt_1500", 50_000, 150_000),
        ("lt_3000", 150_000, 300_000),
        ("lt_5000", 300_000, 500_000),
    ]


def _sample_total_cents(rng: random.Random, bucket: str) -> int:
    ranges = {name: (lo, hi) for name, lo, hi in _bucket_ranges()}
    lo, hi = ranges.get(bucket, (45_00, 320_000))
    # Triangular distribution with a mild bias towards the lower end of the bucket.
    mode = lo + int((hi - lo) * 0.35)
    v = int(rng.triangular(lo, hi - 1, mode))
    return max(1, v)


def _persona_defs() -> Dict[str, Dict[str, Any]]:
    # We use personas only to produce believable order totals distribution.
    # They do not imply identity; they are synthetic labels for demo dashboards.
    return {
        "high_school": {"weights": {"lt_100": 0.55, "lt_500": 0.35, "lt_1500": 0.10, "lt_3000": 0.0, "lt_5000": 0.0}},
        "university": {"weights": {"lt_100": 0.25, "lt_500": 0.40, "lt_1500": 0.30, "lt_3000": 0.05, "lt_5000": 0.0}},
        "gamer": {"weights": {"lt_100": 0.05, "lt_500": 0.25, "lt_1500": 0.40, "lt_3000": 0.25, "lt_5000": 0.05}},
        "office_worker": {"weights": {"lt_100": 0.10, "lt_500": 0.35, "lt_1500": 0.40, "lt_3000": 0.12, "lt_5000": 0.03}},
        "pro_creator": {"weights": {"lt_100": 0.0, "lt_500": 0.10, "lt_1500": 0.30, "lt_3000": 0.35, "lt_5000": 0.25}},
    }


def _choose_weighted(rng: random.Random, weights: Dict[str, float]) -> str:
    items = [(k, float(v)) for k, v in (weights or {}).items() if float(v) > 0.0]
    if not items:
        return "lt_1500"
    total = sum(w for _, w in items)
    pick = rng.random() * total
    cur = 0.0
    for k, w in items:
        cur += w
        if pick <= cur:
            return k
    return items[-1][0]


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


def seed_orders(*, count: int, uid: str, days: int, seed: int, start: datetime | None, end: datetime | None, truncate: bool) -> dict:
    rng = random.Random(int(seed))
    with db_session() as db:
        _ensure_basics(db)

        if truncate:
            # Destructive: only runs when caller explicitly passes --truncate.
            db.execute(text("DELETE FROM order_sessions"))
            db.execute(text("DELETE FROM orders"))
            db.commit()

        existing = int(db.execute(text("SELECT COUNT(*) FROM orders")).scalar() or 0)
        created = 0
        statuses = ["paid", "paid", "paid", "refunded", "chargeback", "pending_payment"]
        currencies = ["USD", "USD", "USD", "AUD"]

        personas = _persona_defs()
        persona_keys = list(personas.keys())

        # Ensure a stable set of synthetic customers for personas.
        customer_ids: Dict[str, str] = {}
        for p in persona_keys:
            email = f"demo+{p}@shopsquire.local"
            row = db.execute(text("SELECT id FROM customers WHERE email = :email LIMIT 1"), {"email": email}).fetchone()
            if row:
                customer_ids[p] = str(row[0])
                continue
            cid = _uuid()
            db.execute(
                text("INSERT INTO customers (id, email, name, phone, created_at) VALUES (:id, :email, :name, :phone, :created_at)"),
                {
                    "id": cid,
                    "email": email,
                    "name": f"Demo {p.replace('_', ' ').title()}",
                    "phone": "555-0000",
                    "created_at": _utcnow(),
                },
            )
            customer_ids[p] = cid

        # Date range config: prefer explicit start/end, else use days window.
        if start and end and end > start:
            dt_start, dt_end = start, end
        else:
            dt_end = _utcnow()
            dt_start = dt_end - timedelta(days=max(1, int(days)))

        bucket_counts: Dict[str, int] = {name: 0 for name, _, _ in _bucket_ranges()}
        persona_counts: Dict[str, int] = {p: 0 for p in persona_keys}

        for _ in range(int(count)):
            order_id = _uuid()
            persona = rng.choice(persona_keys)
            persona_counts[persona] = persona_counts.get(persona, 0) + 1
            bucket = _choose_weighted(rng, personas.get(persona, {}).get("weights") or {})
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1

            created_at = _rand_dt_between(rng, dt_start, dt_end)
            total = _sample_total_cents(rng, bucket)
            status = rng.choice(statuses)
            currency = rng.choice(currencies)
            cid = customer_ids.get(persona) or next(iter(customer_ids.values()))

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
            "bucket_counts": bucket_counts,
            "persona_counts": persona_counts,
            "uid": uid,
            "days": days,
            "seed": seed,
            "start": dt_start.date().isoformat(),
            "end": dt_end.date().isoformat(),
            "truncate": bool(truncate),
        }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=700)
    ap.add_argument("--uid", type=str, default="demo-user-1")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--start", type=str, default=None, help="Start date (YYYY-MM-DD). Overrides --days when used with --end.")
    ap.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD). Overrides --days when used with --start.")
    ap.add_argument("--truncate", action="store_true", help="Delete existing orders + order_sessions first (destructive).")
    args = ap.parse_args()

    if args.count <= 0:
        raise SystemExit("--count must be > 0")
    start = _parse_date(args.start)
    end = _parse_date(args.end)
    out = seed_orders(count=args.count, uid=args.uid, days=args.days, seed=args.seed, start=start, end=end, truncate=bool(args.truncate))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
