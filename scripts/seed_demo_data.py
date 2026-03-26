import json
import uuid
import re
import os
from pathlib import Path
from datetime import datetime, timedelta
import sys

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.models.db import db_session


def _uuid() -> str:
    return str(uuid.uuid4())

_PRICE_RE = re.compile(r"price\s*:?\s*\$?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_RAM_RE = re.compile(r"(\d+)\s*GB\s*RAM", re.IGNORECASE)
_STORAGE_RE = re.compile(r"(\d+)\s*(TB|GB)\s*(?:SSD|storage|M\.2|HDD)", re.IGNORECASE)
_BRACKET_STORAGE_RE = re.compile(r"\[(\d+)\s*(TB|GB)\]", re.IGNORECASE)
_SCREEN_RE = re.compile(r"(\d{1,2}(?:\.\d)?)\"")


def _default_product_source() -> str:
    for candidate in (
        "docs/laptop-products-new-short.txt",
        "docs/laptop-products-new.txt",
        "docs/laptop-products-exp.txt",
    ):
        if Path(candidate).exists():
            return candidate
    return "docs/laptop-products-new.txt"


def _split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(":::"):
            if current:
                blocks.append(current)
                current = []
            continue
        if not stripped:
            continue
        current.append(line.rstrip())
    if current:
        blocks.append(current)
    return blocks


def parse_laptop_products(path: str | None = None) -> list[dict]:
    p = Path(path or _default_product_source())
    if not p.exists():
        return []
    text_data = p.read_text(encoding="utf-8", errors="ignore")
    products: list[dict] = []
    for block in _split_blocks(text_data):
        title_lines: list[str] = []
        price = None
        spec_lines: list[str] = []
        in_title = True
        for line in block:
            stripped = line.strip()
            if not stripped:
                continue
            if _PRICE_RE.search(stripped):
                m = _PRICE_RE.search(stripped)
                price = float(m.group(1)) if m else price
                in_title = False
                continue
            if stripped.lower().startswith("key features"):
                in_title = False
                continue
            if in_title:
                title_lines.append(stripped)
            else:
                spec_lines.append(stripped)
        name = " ".join([line.strip() for line in title_lines if line.strip()]).strip()
        if not name or price is None:
            continue
        display_name = title_lines[0].strip() if title_lines else name
        subtitle = " ".join([line.strip() for line in title_lines[1:] if line.strip()]).strip() or None
        spec_text = " ".join(spec_lines)
        ram_gb = None
        ram_match = _RAM_RE.search(spec_text)
        if ram_match:
            ram_gb = int(ram_match.group(1))
        storage = None
        storage_match = _STORAGE_RE.search(spec_text)
        if storage_match:
            storage = f"{storage_match.group(1)}{storage_match.group(2).upper()}"
        if not storage:
            bmatch = _BRACKET_STORAGE_RE.search(name)
            if bmatch:
                storage = f"{bmatch.group(1)}{bmatch.group(2).upper()}"
        screen = None
        smatch = _SCREEN_RE.search(spec_text + " " + name)
        if smatch:
            screen = smatch.group(1) + "\""

        cpu = next((l for l in spec_lines if "processor" in l.lower() or "snapdragon" in l.lower()), None)
        display = next((l for l in spec_lines if "display" in l.lower() or "oled" in l.lower()), None)
        graphics = next((l for l in spec_lines if "graphics" in l.lower()), None)
        wifi = next((l for l in spec_lines if "wi-fi" in l.lower() or "wifi" in l.lower()), None)
        bluetooth = next((l for l in spec_lines if "bluetooth" in l.lower()), None)
        os_line = next((l for l in spec_lines if "windows" in l.lower() or "os" in l.lower()), None)
        ports = [l for l in spec_lines if "usb" in l.lower() or "hdmi" in l.lower() or "thunderbolt" in l.lower() or "sd" in l.lower()]
        products.append(
            {
                "name": name.strip(),
                "price_cents": int(round(float(price) * 100)),
                "specs": {
                    "display_name": display_name,
                    "subtitle": subtitle,
                    "display": display,
                    "screen": screen,
                    "cpu": cpu,
                    "ram_gb": ram_gb,
                    "storage": storage,
                    "graphics": graphics,
                    "ports": ports,
                    "os": os_line,
                    "wifi": wifi,
                    "bluetooth": bluetooth,
                },
            }
        )
    return products


def _rating_for_price(price_cents: int) -> float:
    price = price_cents / 100
    rating = 4.1 + min(price / 5000.0, 0.8)
    return round(min(rating, 4.9), 1)


def _shipping_days_for_price(price_cents: int) -> int:
    price = price_cents / 100
    if price < 900:
        return 3
    if price < 1500:
        return 3
    if price < 2500:
        return 4
    return 5


def _stock_for_price(price_cents: int) -> int:
    price = price_cents / 100
    if price < 900:
        return 18
    if price < 1500:
        return 14
    if price < 2500:
        return 9
    return 5


def _svg_for_name(name: str) -> str:
        # Simple SVG placeholder with product name text
        safe = (name or "Product").replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        label = safe if len(safe) <= 30 else safe[:27] + '...'
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="600" height="400" viewBox="0 0 600 400">
    <rect width="100%" height="100%" fill="#f3f4f6" />
    <rect x="16" y="16" width="568" height="368" rx="8" fill="#e5e7eb" />
    <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" font-size="24" fill="#111827">{label}</text>
</svg>'''


def _ensure_accessories(db, static_root: Path) -> None:
    accessories = [
        {"sku": "ACC-USB-HUB", "name": "USB-C Hub", "price_cents": 4900, "specs": {"category": "usb_hub", "tags": ["usb_hub", "student", "office", "creator"]}},
        {"sku": "BAG-SLEEVE-15", "name": "Laptop Sleeve 15 inch", "price_cents": 2900, "specs": {"category": "laptop_sleeve", "tags": ["laptop_sleeve", "student", "office", "travel"]}},
        {"sku": "PERIPH-MOUSE-WL", "name": "Wireless Mouse", "price_cents": 3900, "specs": {"category": "mouse", "tags": ["mouse", "student", "office_general", "university_general"]}},
        {"sku": "ACC-SSD-1TB", "name": "1TB External SSD", "price_cents": 12900, "specs": {"category": "external_ssd", "tags": ["external_ssd", "creator", "engineering_student", "content_creator"]}},
        {"sku": "ACC-DOCK-USB-C", "name": "USB-C Docking Station", "price_cents": 14900, "specs": {"category": "dock", "tags": ["dock", "office_general", "business_professional", "developer"]}},
        {"sku": "MON-27-QHD", "name": "27 inch QHD Productivity Monitor", "price_cents": 24900, "specs": {"category": "monitor", "tags": ["monitor", "office_finance", "computer_science_student", "content_creator"]}},
        {"sku": "HEAD-NC-01", "name": "Noise Cancelling Headset", "price_cents": 11900, "specs": {"category": "headset", "tags": ["headset", "business_professional", "gaming_casual", "music_production"]}},
        {"sku": "COOL-PAD-01", "name": "Cooling Pad", "price_cents": 5900, "specs": {"category": "cooling_pad", "tags": ["cooling_pad", "gaming_competitive", "gaming_aaa_heavy"]}},
        {"sku": "COOL-STAND-01", "name": "Adjustable Laptop Stand", "price_cents": 4500, "specs": {"category": "laptop_stand", "tags": ["laptop_stand", "office_general", "creator", "student"]}},
        {"sku": "PERIPH-GMOUSE-01", "name": "RGB Gaming Mouse", "price_cents": 6900, "specs": {"category": "gaming_mouse", "tags": ["gaming_mouse", "gaming_competitive", "gaming_aaa_heavy"]}},
        {"sku": "ACC-CHARGER-100W", "name": "100W Compact Charger", "price_cents": 7900, "specs": {"category": "compact_charger", "tags": ["compact_charger", "office_executive", "student", "travel"]}},
        {"sku": "ACC-PBANK-20K", "name": "20,000mAh USB-C Power Bank", "price_cents": 8900, "specs": {"category": "power_bank", "tags": ["power_bank", "office_executive", "university_general", "medical_student"]}},
        {"sku": "ACC-CABLE-USB-C", "name": "Extra USB-C Charging Cable", "price_cents": 1900, "specs": {"category": "extra_charging_cable", "tags": ["extra_charging_cable", "medical_student", "note_taking_student"]}},
        {"sku": "ACC-STYLUS-01", "name": "Precision Stylus Pen", "price_cents": 5900, "specs": {"category": "stylus", "tags": ["stylus", "design_student", "architecture_student", "note_taking_student"]}},
        {"sku": "ACC-CARDREADER-01", "name": "USB-C SD Card Reader", "price_cents": 3900, "specs": {"category": "card_reader", "tags": ["card_reader", "content_creator", "photography"]}},
        {"sku": "ACC-AUDIO-IF-01", "name": "Compact Audio Interface", "price_cents": 15900, "specs": {"category": "audio_interface", "tags": ["audio_interface", "music_production", "creator"]}},
    ]
    for acc in accessories:
        exists = db.execute(text("SELECT 1 FROM products WHERE sku = :sku"), {"sku": acc["sku"]}).scalar()
        if exists:
            continue
        pid = _uuid()
        svg_path = static_root / f"{acc['sku']}.svg"
        if not svg_path.exists():
            try:
                svg_content = _svg_for_name(acc["name"])
                svg_path.write_text(svg_content, encoding="utf-8")
            except Exception:
                pass
        image_url = f"/static/images/{acc['sku']}.svg"
        db.execute(
            text(
                "INSERT INTO products (id, sku, name, price_cents, currency, image_url, specs, active, updated_at) "
                "VALUES (:id, :sku, :name, :price, 'USD', :image_url, :specs, true, :updated_at)"
            ),
            {
                "id": pid,
                "sku": acc["sku"],
                "name": acc["name"],
                "price": acc["price_cents"],
                "image_url": image_url,
                "specs": json.dumps({"rating": 4.6, "shipping_days": 2, **(acc.get("specs") or {})}),
                "updated_at": datetime.utcnow(),
            },
        )
        db.execute(
            text(
                "INSERT INTO inventory (id, product_id, stock, warehouse, updated_at) "
                "VALUES (:id, :product_id, :stock, :warehouse, :updated_at)"
            ),
            {
                "id": _uuid(),
                "product_id": pid,
                "stock": 50,
                "warehouse": "default",
                "updated_at": datetime.utcnow(),
            },
        )


def seed_customers(db):
    existing = db.execute(text("SELECT COUNT(*) FROM customers")).scalar() or 0
    if existing > 0:
        return
    rows = [
        (_uuid(), "alex@example.com", "Alex Carter", "555-0101"),
        (_uuid(), "jamie@example.com", "Jamie Lee", "555-0199"),
    ]
    for r in rows:
        db.execute(
            text("INSERT INTO customers (id, email, name, phone, created_at) VALUES (:id, :email, :name, :phone, :created_at)"),
            {"id": r[0], "email": r[1], "name": r[2], "phone": r[3], "created_at": datetime.utcnow()},
        )


def seed_products(db):
    existing = db.execute(text("SELECT COUNT(*) FROM products")).scalar() or 0
    static_root = Path("static") / "images"
    try:
        static_root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    default_source = _default_product_source()
    source_path = os.getenv("PRODUCT_SOURCE_TXT", default_source)
    parsed = parse_laptop_products(source_path)
    # If products already seeded, ensure any missing image_url values are populated
    if existing > 0:
        try:
            rows = db.execute(text("SELECT sku FROM products")).mappings().all()
            for r in rows:
                sku = r.get("sku")
                if not sku:
                    continue
                svg_path = static_root / f"{sku}.svg"
                if not svg_path.exists():
                    try:
                        # try to derive human name from sku via existing fallback docs
                        name = None
                        parsed_docs = parse_laptop_products()
                        for idx, it in enumerate(parsed_docs, start=1):
                            if f"LAP-{idx:04d}" == sku:
                                name = it.get("name")
                                break
                        svg_content = _svg_for_name(name or sku)
                        svg_path.write_text(svg_content, encoding="utf-8")
                    except Exception:
                        pass
                try:
                    db.execute(text("UPDATE products SET image_url = :url WHERE sku = :sku"), {"url": f"/static/images/{sku}.svg", "sku": sku})
                except Exception:
                    pass
        except Exception:
            pass
        if parsed:
            parsed_by_sku = {}
            for idx, item in enumerate(parsed, start=1):
                parsed_by_sku[f"LAP-{idx:04d}"] = item
                parsed_by_sku[f"SYN-LAP-{idx:04d}"] = item
            try:
                rows = db.execute(text("SELECT sku, specs FROM products WHERE sku LIKE 'LAP-%' OR sku LIKE 'SYN-LAP-%'")).mappings().all()
                for row in rows:
                    sku = str(row.get("sku") or "").strip()
                    parsed_item = parsed_by_sku.get(sku)
                    if not parsed_item:
                        continue
                    merged_specs = {}
                    raw_specs = row.get("specs")
                    if isinstance(raw_specs, dict):
                        merged_specs.update(raw_specs)
                    elif isinstance(raw_specs, str):
                        try:
                            loaded = json.loads(raw_specs)
                            if isinstance(loaded, dict):
                                merged_specs.update(loaded)
                        except Exception:
                            pass
                    merged_specs.update(parsed_item.get("specs") or {})
                    db.execute(
                        text("UPDATE products SET name = :name, specs = :specs, updated_at = :updated_at WHERE sku = :sku"),
                        {
                            "sku": sku,
                            "name": parsed_item["name"],
                            "specs": json.dumps(merged_specs),
                            "updated_at": datetime.utcnow(),
                        },
                    )
            except Exception:
                pass
        _ensure_accessories(db, static_root)
        return
    if not parsed:
        parsed = [
            {"name": "Dell XPS 13 Plus Laptop", "price_cents": 129900, "specs": {"ram_gb": 16, "storage": "512GB"}},
            {"name": "Lenovo ThinkPad X1 Carbon Laptop", "price_cents": 119900, "specs": {"ram_gb": 16, "storage": "512GB"}},
            {"name": "Apple MacBook Pro 14 Laptop", "price_cents": 209900, "specs": {"ram_gb": 16, "storage": "512GB"}},
            {"name": "ASUS ZenBook 14 Laptop", "price_cents": 124900, "specs": {"ram_gb": 16, "storage": "512GB"}},
            {"name": "HP EliteBook 840 Laptop", "price_cents": 149900, "specs": {"ram_gb": 16, "storage": "512GB"}},
        ]
    for idx, item in enumerate(parsed, start=1):
        sku = f"LAP-{idx:04d}"
        name = item["name"]
        price = int(item["price_cents"])
        rating = _rating_for_price(price)
        ship_days = _shipping_days_for_price(price)
        specs = item.get("specs") or {}
        specs.update({"rating": rating, "shipping_days": ship_days, "category": "laptop", "tags": ["laptop", "primary_device"]})
        # Create a lightweight local SVG image for the product (small, text-based)
        svg_path = static_root / f"{sku}.svg"
        if not svg_path.exists():
            try:
                svg_content = _svg_for_name(name)
                svg_path.write_text(svg_content, encoding="utf-8")
            except Exception:
                pass
        image_url = f"/static/images/{sku}.svg"
        pid = _uuid()
        db.execute(
            text(
                "INSERT INTO products (id, sku, name, price_cents, currency, image_url, specs, active, updated_at) "
                "VALUES (:id, :sku, :name, :price, 'USD', :image_url, :specs, true, :updated_at)"
            ),
            {
                "id": pid,
                "sku": sku,
                "name": name,
                "price": price,
                "image_url": image_url,
                "specs": json.dumps(specs),
                "updated_at": datetime.utcnow(),
            },
        )
        db.execute(
            text(
                "INSERT INTO inventory (id, product_id, stock, warehouse, updated_at) "
                "VALUES (:id, :product_id, :stock, :warehouse, :updated_at)"
            ),
            {
                "id": _uuid(),
                "product_id": pid,
                "stock": _stock_for_price(price),
                "warehouse": "default",
                "updated_at": datetime.utcnow(),
            },
        )

    # Ensure accessory products exist for cart persistence
    _ensure_accessories(db, static_root)


def seed_orders(db):
    existing = db.execute(text("SELECT COUNT(*) FROM orders")).scalar() or 0
    if existing > 0:
        return
    cust = db.execute(text("SELECT id FROM customers ORDER BY created_at DESC LIMIT 1")).fetchone()
    if not cust:
        return
    cid = cust[0]
    order_ids = []
    for i in range(3):
        order_id = _uuid()
        order_ids.append(order_id)
        db.execute(
            text(
                "INSERT INTO orders (id, customer_id, total_cents, currency, status, created_at, updated_at) "
                "VALUES (:id, :customer_id, :total_cents, :currency, :status, :created_at, :updated_at)"
            ),
            {
                "id": order_id,
                "customer_id": cid,
                "total_cents": 129900 + i * 35000,
                "currency": "USD",
                "status": "paid",
                "created_at": datetime.utcnow() - timedelta(days=i + 1),
                "updated_at": datetime.utcnow() - timedelta(days=i + 1),
            },
        )
    for oid in order_ids:
        db.execute(
            text("INSERT INTO order_sessions (id, uid, order_id) VALUES (:id, :uid, :order_id)"),
            {"id": _uuid(), "uid": "vip-user-42", "order_id": oid},
        )

    # Seed order_items so _corroborate_order() finds real purchase history.
    # Without this the fraud check silently returns db_unavailable in demo env.
    _demo_items = [
        ("LAPTOP-LENOVO-001", "Lenovo ThinkPad X1 Carbon", "lenovo", 149900),
        ("LAPTOP-DELL-001",   "Dell XPS 15",               "dell",   179900),
        ("LAPTOP-APPLE-001",  "Apple MacBook Pro 14",       "apple",  199900),
    ]
    try:
        for idx, (oid, (sku, product_name, brand, unit_price)) in enumerate(
            zip(order_ids, _demo_items)
        ):
            db.execute(
                text(
                    "INSERT INTO order_items "
                    "(id, order_id, user_id, sku, product_name, brand, quantity, unit_price_cents, created_at, updated_at) "
                    "VALUES (:id, :order_id, :user_id, :sku, :product_name, :brand, 1, :unit_price, :created_at, :updated_at) "
                    "ON CONFLICT (id) DO NOTHING"
                ),
                {
                    "id": _uuid(),
                    "order_id": oid,
                    "user_id": cid,
                    "sku": sku,
                    "product_name": product_name,
                    "brand": brand,
                    "unit_price": unit_price,
                    "created_at": (datetime.utcnow() - timedelta(days=idx + 1)).isoformat(),
                    "updated_at": (datetime.utcnow() - timedelta(days=idx + 1)).isoformat(),
                },
            )
    except Exception:
        pass  # Table may not exist yet in older envs; migration handles it


def seed_decisions(db):
    existing = db.execute(text("SELECT COUNT(*) FROM decision_logs")).scalar() or 0
    if existing > 0:
        return
    for i in range(7):
        decision_id = _uuid()
        db.execute(
            text(
                "INSERT INTO decision_logs (id, agent_name, valid_from, input_data, proposed_action, policy_version, approval_required, execution_status) "
                "VALUES (:id, :agent_name, :valid_from, :input_data, :proposed_action, :policy_version, :approval_required, :execution_status)"
            ),
            {
                "id": decision_id,
                "agent_name": "recommendation-agent",
                "valid_from": datetime.utcnow() - timedelta(days=i),
                "input_data": json.dumps({"user_query": "Show me laptops under $1500"}),
                "proposed_action": json.dumps({"decision_mode": "agent_rerank"}),
                "policy_version": "v1",
                "approval_required": False,
                "execution_status": "executed",
            },
        )


def seed_security_events(db):
    existing = db.execute(text("SELECT COUNT(*) FROM security_events")).scalar() or 0
    if existing > 0:
        return
    sample = [
        ("high", 78, "/api/v1/recommend/suggest", ["AML.T0043"]),
        ("warn", 42, "/api/v1/pricing/suggest", ["AML.T0020"]),
        ("info", 10, "/api/v1/support/answer", []),
    ]
    for idx, (sev, score, path, mitre) in enumerate(sample):
        db.execute(
            text(
                "INSERT INTO security_events (id, event_time, path, severity, verdict_score, details) "
                "VALUES (:id, :event_time, :path, :severity, :verdict_score, :details)"
            ),
            {
                "id": _uuid(),
                "event_time": datetime.utcnow() - timedelta(hours=idx * 2),
                "path": path,
                "severity": sev,
                "verdict_score": score,
                "details": json.dumps({"analysis": {"mitre_atlas": mitre}, "payload": {"path": path}}),
            },
        )


def seed_rules(db):
    existing = 0
    try:
        existing = db.execute(text("SELECT COUNT(*) FROM rule_definitions")).scalar() or 0
    except Exception:
        existing = 0
    if existing > 0:
        return
    rules = [
        {"id": "demo_return_request", "title": "return_request", "pattern": r"\\b(return|refund|exchange)\\b", "priority": 10},
        {"id": "demo_order_status", "title": "order_status", "pattern": r"\\b(track|where\\s+is\\s+my\\s+order|order\\s+status)\\b", "priority": 20},
        {"id": "demo_product_search", "title": "product_search", "pattern": r"\\b(show\\s+me|find|search\\s+for|looking\\s+for)\\b", "priority": 30},
    ]
    for r in rules:
        try:
            db.execute(
                text(
                    "INSERT INTO rule_definitions (id, tenant_id, title, pattern, expression, priority, active, created_by, version, created_at) "
                    "VALUES (:id, NULL, :title, :pattern, NULL, :priority, 1, 'seed_demo', 'v1', CURRENT_TIMESTAMP)"
                ),
                r,
            )
        except Exception:
            pass


def main():
    with db_session() as db:
        seed_customers(db)
        seed_products(db)
        seed_orders(db)
        seed_decisions(db)
        seed_security_events(db)
        seed_rules(db)
        db.commit()
    print("Demo data seeded.")


if __name__ == "__main__":
    main()
