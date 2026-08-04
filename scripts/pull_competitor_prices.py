"""Pull configured competitor prices (Phase B of the market-intel plan).

Reads config/competitor_sources.json (per-SKU product-page URLs you pasted from your browser),
honours robots.txt, rate-limits, validates each page matches OUR product, records observations with
jsonld:<domain> provenance, then optionally runs the market pipeline so findings refresh.

Usage:  python scripts/pull_competitor_prices.py [--refresh]
Set "enabled": true in the config (and fill product_urls) before running.
"""
from __future__ import annotations

import sys
from datetime import datetime

sys.path.insert(0, ".")

from src.app.models.db import db_session
from src.app.services.connectors.competitor_price_fetch import fetch_and_record


def main() -> None:
    with db_session() as db:
        out = fetch_and_record(db, observed_at=datetime.now().isoformat(timespec="seconds"))
    print("competitor pull:", out)
    if out.get("disabled"):
        print("→ set \"enabled\": true and fill product_urls in config/competitor_sources.json first")
        return
    if "--refresh" in sys.argv and out.get("recorded"):
        from src.app.services.market_pipeline import run_pipeline
        with db_session() as db:
            r = run_pipeline(db)
        print("pipeline refresh:", {k: r.get(k) for k in ("ingested", "findings", "persisted")})


if __name__ == "__main__":
    main()
