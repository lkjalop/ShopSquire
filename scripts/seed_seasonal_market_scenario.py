"""Seed an isolated Jan-Mar AU back-to-school market scenario."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from src.app.models.db import db_session
from src.app.services.market_facts import record_atp_fact, record_marketing_event
from src.app.services.market_metrics import summarize_marketing_facts
from src.app.services.seasonal_market_scenario import build_back_to_school_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default="synthetic-au-school-2026")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--products", type=int, default=12)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if not args.tenant.startswith("synthetic-"):
        parser.error("--tenant must start with synthetic-")
    with db_session() as db:
        if args.replace:
            db.execute(text("DELETE FROM marketing_event_fact WHERE tenant_id=:tenant"), {"tenant": args.tenant})
            db.execute(text("DELETE FROM inventory_atp_fact WHERE tenant_id=:tenant"), {"tenant": args.tenant})
            db.commit()
        products = [dict(row) for row in db.execute(text("""
            SELECT sku, name, price_cents, currency FROM products
            WHERE COALESCE(active,1)=1 AND currency='AUD' AND price_cents IS NOT NULL
            ORDER BY sku
        """)).mappings().all()]
        scenario = build_back_to_school_scenario(
            products, tenant_id=args.tenant, year=args.year, max_products=args.products,
        )
        marketing_written = sum(int(record_marketing_event(db, fact, commit=False))
                                for fact in scenario["marketing"])
        atp_written = sum(int(record_atp_fact(db, fact, commit=False)) for fact in scenario["atp"])
        db.commit()
        summary = summarize_marketing_facts(db, tenant_id=args.tenant)
    print(json.dumps({
        "tenant_id": args.tenant, "scenario": "au-back-to-school-v1",
        "marketing_written": marketing_written, "atp_written": atp_written,
        "event_count": summary["event_count"], "funnel": summary["funnel"],
        "month_cohorts": summary["month_cohorts"], "insights": summary["insights"],
        "production_canary_equivalent": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
