"""R9.5 — backfill products.brand from the title's leading brand token (one-time seed hygiene).

The demo catalog carries brand ONLY inside titles ("ASUS ROG Strix G16 ..."), so
ProductCard.brand is '' everywhere: brand filtering ("only Asus") can't work and the quality
gate's diversity metric reads null. This backfills the DATA (truth lives in the catalog row)
instead of adding a runtime title-parser — a second decision surface that would live forever.

Honesty rules:
  • the brand list is EXPLICIT and reviewable below (store-profile known_brands + brands
    evident in this catalog's own titles) — no fuzzy inference;
  • match anchored at the title START (after stripping (R)/(TM) marks), longest-brand-first;
  • the stored value is the EXACT substring from the title (preserves ASUS / TP-Link casing);
  • no match → brand stays NULL (generic pharmacy/fashion items are genuinely unbranded);
  • only NULL/'' rows are touched; reruns are no-ops.

Usage:  python scripts/backfill_brand_from_title.py [--apply]   (default = dry-run)
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "tmp" / "demo.sqlite"

# catalog-evident brands not (yet) in the profile's known_brands — reviewable data
EXTRA_BRANDS = [
    "seagate", "sandisk", "wd", "western digital", "thule", "stm", "logitech", "jbl", "bose",
    "blaupunkt", "aoc", "tp-link", "netgear", "starlink", "rig", "corsair", "hyperx",
    "acezone", "epson", "canon", "generation earth",
]

_MARKS = re.compile(r"[®™]")   # ® ™ glued to brand tokens ("SanDisk®", "Nighthawk®")


def _brand_list() -> list:
    prof = json.loads((REPO / "config/store_profiles/electronics.json").read_text(encoding="utf-8"))
    return sorted(set(prof.get("known_brands") or []) | set(EXTRA_BRANDS), key=len, reverse=True)


def match_brand(title: str, brands: list) -> str | None:
    """Exact title substring for the FIRST (longest) brand whose token leads the title."""
    clean = _MARKS.sub("", title or "")
    low = clean.lower()
    for b in brands:
        if low.startswith(b + " "):
            return clean[: len(b)]      # the title's own casing
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write updates (default: dry-run)")
    args = ap.parse_args()
    brands = _brand_list()
    con = sqlite3.connect(str(DB))
    cur = con.cursor()
    cur.execute("SELECT sku, name FROM products WHERE brand IS NULL OR brand = ''")
    rows = cur.fetchall()
    updates, skipped = [], []
    for sku, name in rows:
        b = match_brand(name or "", brands)
        (updates.append((b, sku)) if b else skipped.append((sku, name)))
    print(f"{len(rows)} NULL-brand rows: {len(updates)} backfillable, {len(skipped)} stay NULL")
    for b, sku in updates[:15]:
        print(f"  {sku:16} -> {b}")
    if len(updates) > 15:
        print(f"  ... and {len(updates) - 15} more")
    if args.apply and updates:
        cur.executemany("UPDATE products SET brand = ? WHERE sku = ? AND (brand IS NULL OR brand = '')",
                        updates)
        con.commit()
        print(f"APPLIED {cur.rowcount if cur.rowcount != -1 else len(updates)} updates")
    elif updates:
        print("dry-run (pass --apply to write)")
    con.close()


if __name__ == "__main__":
    main()
