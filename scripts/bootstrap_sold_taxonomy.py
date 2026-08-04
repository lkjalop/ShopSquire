"""Bootstrap the demo tenant's sold-taxonomy (V2 Phase 2 exit) — a MANUAL approximation of
what T3 auto-classification + T4 merchant approval will produce properly.

Maps each demo SKU family (inferred from SKU prefix — the live catalog has NO category or
product_type data on any of its 114 products) to its Shopify taxonomy node, grants those
nodes as sold (source=demo_bootstrap), then proves the is_sold() ground truth that regrounds
off-catalog honesty. Idempotent; rollback = DELETE FROM sold_taxonomy WHERE source='demo_bootstrap'.

Run from repo root: python scripts/bootstrap_sold_taxonomy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import sessionmaker

from src.app.models.db import get_engine
from src.app.services.taxonomy_registry import add_sold_node, get_node, is_sold, sold_summary

# SKU-prefix family -> pinned-release node handle (release 2026-05)
DEMO_SOLD_NODES = {
    "LAP": "el-6-6",       # Electronics > Computers > Laptops (45 SKUs)
    "MON": "el-17-1",      # Electronics > Video > Computer Monitors (10)
    "TAB": "el-6-8",       # Electronics > Computers > Tablet Computers (6)
    "NET": "el-12-1",      # Electronics > Networking > Bridges & Routers (7) — consumer
                           #   routers sold; el-12-3 Hubs & Switches deliberately NOT granted
    "AUD": "el-2-2-7",     # Electronics > Audio > ... > Headphones & Headsets (6)
    "PRN": "el-13-4",      # Electronics > ... > Printers, Copiers & Fax Machines (2)
    "HDD": "el-7-9-14",    # Electronics > ... > Computer Components > Storage Devices (9)
    "BAG": "lb-15",        # Luggage & Bags > Laptop Bags (4)
    "PHM": "hb-1-9-6",     # Health & Beauty > ... > Vitamins & Supplements (12)
    "FSH": "aa-1",         # Apparel & Accessories > Clothing (12 — mixed apparel)
}

# The probes that define Phase-2 exit: (handle, expected, why)
ACCEPTANCE = [
    ("el-6-6", True, "Laptops — the store's core"),
    ("el-6-2", False, "Computer Servers — the $80k A100 rack-server case, now a FACT not a regex"),
    ("el-12-1-4", True, "Wireless Routers — descendant of granted Bridges & Routers"),
    ("el-12-3", False, "Hubs & Switches — 'network switch' refusable while routers sell"),
    ("bi-18", False, "Material Handling — the forklift class the negative list was blind to"),
    ("el-13-1", False, "3D Printer Accessories — sibling of sold Printers, not implied"),
    ("aa-1-4", True, "Dresses — fashion vertical grounded (descendant of Clothing)"),
    ("hb-1-9-6", True, "Vitamins & Supplements — pharmacy vertical grounded"),
    ("el", False, "Electronics root — selling laptops must NOT imply the whole vertical"),
]


def main() -> None:
    s = sessionmaker(bind=get_engine())()
    try:
        for prefix, handle in DEMO_SOLD_NODES.items():
            node = get_node(handle)
            assert node is not None, f"{handle} not in pinned release"
            ok = add_sold_node(s, node_handle=handle, source="demo_bootstrap",
                               approved_by="demo_bootstrap")
            print(f"  grant {prefix:<4} -> {handle:<12} {node.full_path}  [{'ok' if ok else 'FAIL'}]")
        s.commit()

        summary = sold_summary(s)
        print(f"\ngrounded={summary['grounded']} release={summary['release']} "
              f"nodes={len(summary['nodes'])}")

        print("\nACCEPTANCE:")
        failures = 0
        for handle, expected, why in ACCEPTANCE:
            got = is_sold(s, handle)
            mark = "PASS" if got is expected else "FAIL"
            if got is not expected:
                failures += 1
            print(f"  [{mark}] is_sold({handle}) = {got} (expected {expected}) — {why}")
        if failures:
            sys.exit(f"{failures} acceptance probe(s) failed")
        print("\nPhase-2 exit criteria MET.")
    finally:
        s.close()


if __name__ == "__main__":
    main()
