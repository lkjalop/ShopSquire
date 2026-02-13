#!/usr/bin/env python3
"""Parse docs/laptop-products.txt, enrich product data (Options A-D), and upsert into DB.

Creates structured `specs` JSON, adds corporate metadata for some items, and upserts
products and inventory into the SQLite DB used for local E2E.
"""
import re
import os
import json
import uuid
from datetime import datetime, timedelta
from src.app.models.db import db_session

DOC_PATH = os.path.join(os.getcwd(), "docs", "laptop-products.txt")


def read_blocks(path):
    with open(path, "r", encoding="utf8") as f:
        raw = f.read()
    parts = re.split(r"[:]{6,}", raw)
    blocks = [p.strip() for p in parts if p.strip()]
    return blocks


def parse_block(block):
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    title = lines[0]
    price = None
    # find Price: line
    for l in lines[1:6]:
        m = re.search(r"Price\s*:\s*\$?([0-9,]+)", l, re.IGNORECASE)
        if m:
            price = int(m.group(1).replace(",", ""))
            break
    # fallback search
    if price is None:
        m = re.search(r"Price\s*:\s*\$?([0-9,]+)", block, re.IGNORECASE)
        if m:
            price = int(m.group(1).replace(",", ""))
    # collect spec text
    spec_text = "\n".join(lines[1:])
    # heuristics
    brand = title.split()[0]
    model = title[len(brand):].strip()
    screen = None
    m = re.search(r"(\d{2}(?:\.\d)?\")\s*(?:[Ww][Uu][Xx][Gg][Aa]|FHD|WQXGA|WUXGA|UHD|2K|4K)?", title)
    if not m:
        m = re.search(r"(\d{1,2}\.\d|\d{2})\"", block)
    if m:
        screen = m.group(1).strip('"')
    ram = None
    m = re.search(r"(\d{1,3})GB\s+RAM", block, re.IGNORECASE)
    if not m:
        m = re.search(r"(\d{1,3})GB\b", block, re.IGNORECASE)
    if m:
        ram = int(m.group(1))
    storage = None
    m = re.search(r"(\d+)(TB|GB)\s+(?:SSD|M\.2|storage)", block, re.IGNORECASE)
    if m:
        val = int(m.group(1))
        if m.group(2).upper() == "TB":
            val = val * 1024
        storage = val
    cpu = None
    m = re.search(r"(Ryzen\s*[0-9A-Za-z\-\s]+|Intel[^,\n]+|Qualcomm[^,\n]+|Apple[^,\n]+)", block, re.IGNORECASE)
    if m:
        cpu = m.group(1).strip()
    gpu = None
    if re.search(r"RTX|GeForce|Radeon|Iris|Arc|Adreno", block, re.IGNORECASE):
        m = re.search(r"(Nvidia\s+GeForce\s+RTX\s*\d+|GeForce\s+RTX\s*\d+|Nvidia\s+GeForce\s+\w+|AMD\s+Radeon[^,\n]+|Intel\s+Iris[^,\n]+|Intel\s+Arc[^,\n]+|Adreno[^,\n]+)", block, re.IGNORECASE)
        if m:
            gpu = m.group(1).strip()
    touch = bool(re.search(r"Touch|2-in-1|Touchscreen|Convertible", block, re.IGNORECASE))
    refresh = None
    m = re.search(r"(\d{2,3})Hz", block)
    if m:
        refresh = int(m.group(1))
    wifi = None
    m = re.search(r"Wi-?Fi\s*(\d[6]?)", block, re.IGNORECASE)
    if m:
        wifi = m.group(1)
    osys = None
    m = re.search(r"Windows|macOS|macOS|MacBook|Copilot\+ PC|Chrome OS|Linux", block, re.IGNORECASE)
    if m:
        osys = m.group(0)
    ports = []
    ports_map = {"HDMI": r"HDMI", "USB-C": r"USB-C|Thunderbolt", "USB-A": r"USB-A|USB 3", "SD": r"SD card|microSD"}
    for k, rx in ports_map.items():
        if re.search(rx, block, re.IGNORECASE):
            ports.append(k)
    # category heuristics
    category = "consumer"
    if re.search(r"Gaming|RTX|144Hz|165Hz|240Hz|240 Hz|Gamer|OMEN|TUF|Alienware|Legion", block, re.IGNORECASE):
        category = "gaming"
    elif re.search(r"Workstation|UHD\+|UHD|Creat|Creator|Prestige|Ryzen 9|Threadripper|Xeon|M[45]|Pro", block, re.IGNORECASE):
        category = "workstation"
    elif touch or re.search(r"2-in-1|Convertible|Yoga|x360|Surface", block, re.IGNORECASE):
        category = "convertible"
    elif re.search(r"Slim|Thin & Light|Ultrabook|Slim" , block, re.IGNORECASE) or (price and price < 1500 and (ram or storage) and not re.search(r"RTX|Radeon|GeForce", block, re.IGNORECASE)):
        category = "ultrabook"
    elif re.search(r"OmniBook|Enterprise|Copilot\+|vPro|management", block, re.IGNORECASE):
        category = "corporate"
    # user segment
    user_segment = "general"
    if category == "gaming":
        user_segment = "gaming"
    elif category == "workstation":
        user_segment = "creator"
    elif category == "corporate":
        user_segment = "corporate"
    elif category == "convertible":
        user_segment = "touch"

    desc = lines[0]
    specs = {
        "cpu": cpu,
        "ram_gb": ram,
        "storage_gb": storage,
        "gpu": gpu,
        "screen_in": screen,
        "refresh_hz": refresh,
        "touch": touch,
        "wifi": wifi,
        "ports": ports,
        "os": osys,
    }

    return {
        "title": title,
        "brand": brand,
        "model": model,
        "price": price,
        "description": desc,
        "specs": specs,
        "category": category,
        "user_segment": user_segment,
    }


def enrich_products(blocks):
    out = []
    for i, b in enumerate(blocks, start=1):
        p = parse_block(b)
        p["sku"] = f"LP{i:03d}"
        # support contact and warranty heuristics
        p["warranty_months"] = 12 if p["price"] and p["price"] < 1500 else 24
        p["image_url"] = f"https://via.placeholder.com/400x300?text={p['brand']}+{i}"
        p["stock"] = 10 if p["user_segment"] != "workstation" else 3
        # corporate metadata for some
        if p["category"] in ("corporate", "workstation") or (p["price"] and p["price"] > 3000):
            p["tpm"] = True
            p["management_agent_installed"] = True
            p["asset_tag"] = f"AT-{uuid.uuid4().hex[:8]}"
            p["lease_expiry_date"] = (datetime.utcnow() + timedelta(days=365 * 2)).isoformat()
            p["purchase_order_id"] = f"PO-{random_id(6)}"
            p["assigned_department"] = "Engineering" if p["user_segment"] == "creator" else "IT"
        else:
            p["tpm"] = False
            p["management_agent_installed"] = False
            p["asset_tag"] = None
        p["support_contact"] = {
            "email": f"support+{p['sku'].lower()}@example.com",
            "phone": "+1-800-555-0100",
        }
        p["average_rating"] = round(3.5 + (i % 5) * 0.3, 2)
        p["reviews_count"] = (i * 7) % 200
        out.append(p)
    return out


def random_id(n=6):
    import random, string
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(n))


def upsert_products(products):
    with db_session() as sess:
        created = 0
        updated = 0
        for p in products:
            sku = p['sku']
            row = sess.execute("SELECT id FROM products WHERE sku = :sku", {"sku": sku}).fetchone()
            specs_json = json.dumps(p['specs'], ensure_ascii=False)
            desc = p.get('description') or p['model']
            price_cents = int((p.get('price') or 0) * 100)
            if row:
                pid = row[0]
                sess.execute("UPDATE products SET name=:name, price_cents=:price, image_url=:img, specs=:specs, active=1 WHERE id=:id",
                             {"name": p['title'], "price": price_cents, "img": p['image_url'], "specs": specs_json, "id": pid})
                updated += 1
            else:
                pid = str(uuid.uuid4())
                sess.execute("INSERT INTO products (id, sku, name, price_cents, currency, image_url, specs, active) VALUES (:id,:sku,:name,:price,'USD',:img,:specs,1)",
                             {"id": pid, "sku": sku, "name": p['title'], "price": price_cents, "img": p['image_url'], "specs": specs_json})
                created += 1
            # inventory
            inv = sess.execute("SELECT id FROM inventory WHERE product_id = :pid", {"pid": pid}).fetchone()
            if inv:
                sess.execute("UPDATE inventory SET stock = :stock WHERE id = :id", {"stock": p['stock'], "id": inv[0]})
            else:
                inv_id = str(uuid.uuid4())
                sess.execute("INSERT INTO inventory (id, product_id, stock, warehouse) VALUES (:id, :pid, :stock, 'default')",
                             {"id": inv_id, "pid": pid, "stock": p['stock']})
        try:
            sess.commit()
        except Exception:
            sess.rollback()
            raise
    print(f"Upserted products: created={created} updated={updated}")


if __name__ == '__main__':
    blocks = read_blocks(DOC_PATH)
    print(f"Parsed {len(blocks)} blocks from {DOC_PATH}")
    products = enrich_products(blocks)
    upsert_products(products)
