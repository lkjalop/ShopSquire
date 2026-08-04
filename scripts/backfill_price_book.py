"""Backfill price_book_entry from the products catalog (A1 of the market-intel plan).

Every active SKU gets an 'our retail' row (channel=default, currency=AUD, source=catalog) so the
competitor-undercut join has our price for EVERY product, not just the 3 demo-seeded SKUs.
Idempotent: fills gaps only unless --overwrite (which still never touches non-catalog-sourced rows).

Usage:  python scripts/backfill_price_book.py [--overwrite]
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from src.app.models.db import db_session
from src.app.services.commerce_catalog import backfill_price_book_from_products


def main() -> None:
    overwrite = "--overwrite" in sys.argv
    with db_session() as db:
        out = backfill_price_book_from_products(db, overwrite=overwrite)
    print(f"price_book backfill: seen={out['seen']} written={out['written']} skipped={out['skipped']}"
          + (" (overwrite)" if overwrite else ""))


if __name__ == "__main__":
    main()
