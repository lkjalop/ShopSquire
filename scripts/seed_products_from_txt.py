#!/usr/bin/env python3
"""
Seed the SQLite/Postgres database with products parsed from a products text file.

Usage (SQLite demo):
  set DATABASE_URL=sqlite:///d:/AI/agentLumen/ShopSquire/tmp/shopsquire.db
  python scripts/seed_products_from_txt.py --source docs/laptop-products-exp.txt

For Postgres (if available):
  set DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/shopsquire
  python scripts/seed_products_from_txt.py --source docs/laptop-products-exp.txt
"""
import argparse
import os
import re
import json
import uuid
from pathlib import Path
from typing import List, Dict
import sys

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.models.db import engine
from src.app.models.init_db import ensure_metadata

def _default_source() -> Path:
    """Canonical product catalog source — SAME preference order as
    seed_demo_data._default_product_source (new-short -> new -> exp) so both seed paths populate the
    SAME catalog and demo results are consistent regardless of which seeder ran. Override with
    --source or PRODUCT_SOURCE_TXT."""
    for candidate in (
        "docs/laptop-products-new-short.txt",
        "docs/laptop-products-new.txt",
        "docs/laptop-products-exp.txt",
    ):
        if Path(candidate).exists():
            return Path(candidate)
    return Path("docs/laptop-products-new-short.txt")


DEFAULT_SOURCE = _default_source()


def parse_blocks(text: str) -> List[str]:
    parts = re.split(r"\n\s*:+\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def parse_product(block: str) -> Dict:
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    name_line = lines[0]
    price = 0.0
    for l in lines:
        m = re.search(r"Price\s*:?\s*\$?\s*(\d+(?:\.\d+)?)", l, re.I)
        if m:
            price = float(m.group(1))
            break
    name = name_line
    # crude brand inference
    brand = (name.split()[0] or 'GEN').upper()
    sku_base = re.sub(r"[^A-Za-z0-9]", "", (brand + '-' + name[:18]).upper())
    sku = sku_base[:12] + '-' + uuid.uuid4().hex[:6].upper()
    specs: Dict[str, str] = {}
    # derive some specs
    def add_spec(k: str, v: str):
        if v:
            specs[k] = v
    # display size
    m = re.search(r"(1[3456](?:\.|\")?\s*(?:inch|\")?)|WQXGA|WUXGA|UHD\+|FHD|2K|4\.5K|OLED", block, re.I)
    add_spec('display', m.group(0) if m else '')
    # cpu
    m = re.search(r"(Intel\s+Core\s+[^\)\n]+|AMD\s+Ryzen[^\)\n]+|Snapdragon[^\)\n]+|M[1-5])", block, re.I)
    add_spec('cpu', m.group(0) if m else '')
    # ram/storage
    m = re.search(r"(\d+GB)\s+RAM", block, re.I)
    add_spec('ram_gb', m.group(1)[:-2] if m else '')
    m = re.search(r"(\d+TB|\d+GB)\s+SSD", block, re.I)
    add_spec('storage', m.group(0) if m else '')
    # graphics
    m = re.search(r"(RTX\s*\d+|Nvidia\s+GeForce[^\n]+|AMD\s+Radeon|Intel\s+Arc|Adreno)", block, re.I)
    add_spec('graphics', m.group(0) if m else '')
    # os
    m = re.search(r"Windows\s+11|macOS|Windows", block, re.I)
    add_spec('os', m.group(0) if m else '')
    # wifi/bluetooth
    m = re.search(r"Wi-?Fi\s*\d(?:E|)|Wi-?Fi\s*7|802\.11\s*[a-z]+", block, re.I)
    add_spec('wifi', m.group(0) if m else '')
    m = re.search(r"Bluetooth\s*v?\d+(?:\.\d+)?", block, re.I)
    add_spec('bluetooth', m.group(0) if m else '')
    # ports list (rough)
    ports = []
    for p in re.findall(r"USB-?C|USB-?A|HDMI|Thunderbolt\s*4|microSD|SD\s*card", block, re.I):
        ports.append(p.upper())
    if ports:
        specs['ports'] = ports
    image_url = f"https://picsum.photos/seed/{sku.lower()}/600/400"
    return {
        'id': str(uuid.uuid4()),
        'sku': sku,
        'name': name,
        'price_cents': int(round(price * 100)),
        'currency': 'USD',
        'image_url': image_url,
        'specs': specs,
        'active': 1,
    }


def main():
    parser = argparse.ArgumentParser(description="Seed product and inventory tables from text catalog.")
    parser.add_argument(
        "--source",
        default=os.getenv("PRODUCT_SOURCE_TXT", str(DEFAULT_SOURCE)),
        help="Path to product source text file.",
    )
    args = parser.parse_args()
    src = Path(args.source)
    if not src.exists():
        print(f"Missing source file: {src}")
        return
    ensure_metadata()
    raw = src.read_text(encoding='utf-8', errors='ignore')
    blocks = parse_blocks(raw)
    products = [parse_product(b) for b in blocks]
    print(f"Parsed {len(products)} products from {src}")
    with engine.begin() as conn:
        for p in products:
            # insert product
            conn.execute(text(
                "INSERT OR REPLACE INTO products (id, sku, name, price_cents, currency, image_url, specs, active, updated_at) "
                "VALUES (:id, :sku, :name, :price_cents, :currency, :image_url, :specs, :active, CURRENT_TIMESTAMP)"
            ), {
                'id': p['id'], 'sku': p['sku'], 'name': p['name'], 'price_cents': p['price_cents'],
                'currency': p['currency'], 'image_url': p['image_url'], 'specs': json.dumps(p['specs'], ensure_ascii=False), 'active': p['active']
            })
            # seed inventory with a small stock
            conn.execute(text(
                "INSERT OR REPLACE INTO inventory (id, product_id, stock, warehouse, updated_at) "
                "VALUES (:id, :pid, :stock, 'default', CURRENT_TIMESTAMP)"
            ), {
                'id': str(uuid.uuid4()), 'pid': p['id'], 'stock': 10
            })
    print('Seeding complete.')


if __name__ == '__main__':
    main()
