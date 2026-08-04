"""Import manually-recorded competitor prices (A2 / Tier-0 of the market-intel plan).

Zero-network, 100%-real data path: record prices you SEE in a browser (JB Hi-Fi, Bing Lee, ...) into a
CSV and import them as competitor_observation rows with honest provenance labels. The market pipeline
then joins them to our price_book retail and detect_competitor_undercut fires on REAL market data —
no scraping, no API keys, no legal surface.

CSV columns (header required):  sku,competitor,price,observed_at
  sku          our catalog SKU (e.g. LAP-01B48B57)
  competitor   retailer domain (e.g. jbhifi.com.au)
  price        their advertised price — dollars (1199.00) or cents (119900); values < 10000 are
               treated as DOLLARS and converted (no AU laptop costs < $100 while cents would be < 10000)
  observed_at  ISO timestamp or date (defaults to today)

Usage:  python scripts/import_competitor_prices.py path/to/prices.csv
        python scripts/import_competitor_prices.py --demo   (writes a template CSV to fill in)
"""
from __future__ import annotations

import csv
import sys
from datetime import date

sys.path.insert(0, ".")

TEMPLATE = """sku,competitor,price,observed_at
LAP-01B48B57,jbhifi.com.au,,
LAP-01B48B57,binglee.com.au,,
LAP-A9A67AB9,jbhifi.com.au,,
LAP-75988087,jbhifi.com.au,,
LAP-433AB371,binglee.com.au,,
"""


def _to_cents(raw: str) -> int | None:
    try:
        v = float(str(raw).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    # dollars vs cents heuristic: < 10000 reads as dollars ($9,999 max laptop), else already cents
    return int(round(v * 100)) if v < 10000 else int(round(v))


def main() -> None:
    if "--demo" in sys.argv:
        with open("competitor_prices_template.csv", "w", newline="", encoding="utf-8") as f:
            f.write(TEMPLATE)
        print("Template written to competitor_prices_template.csv — fill in the prices you see, then:\n"
              "  python scripts/import_competitor_prices.py competitor_prices_template.csv")
        return
    if len(sys.argv) < 2:
        print(__doc__)
        return

    from src.app.models.db import db_session
    from src.app.services.competitor_source import record_observation

    path = sys.argv[1]
    today = date.today().isoformat()
    ok = bad = 0
    with open(path, newline="", encoding="utf-8-sig") as f, db_session() as db:
        for row in csv.DictReader(f):
            sku = str(row.get("sku") or "").strip()
            comp = str(row.get("competitor") or "").strip().lower()
            cents = _to_cents(row.get("price") or "")
            observed = str(row.get("observed_at") or "").strip() or f"{today}T09:00:00"
            if not sku or not comp or cents is None:
                bad += 1
                continue
            # honest provenance: a human recorded this price from the retailer's public page on this date
            if record_observation(db, sku=sku, competitor_price_cents=cents, competitor=comp,
                                  observed_at=observed, source=f"manual:{comp}@{today}"):
                ok += 1
            else:
                bad += 1
        db.commit()
    print(f"imported {ok} observation(s), skipped {bad} bad row(s). "
          f"Next: POST /api/v1/fulfillment/market/refresh (operator) to turn them into findings.")


if __name__ == "__main__":
    main()
