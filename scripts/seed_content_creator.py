"""
Seed the demo SQLite catalog with content creator / video editing laptops.
Run: python scripts/seed_content_creator.py
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = "tmp/demo.sqlite"

CREATOR_LAPTOPS = [
    {
        "sku": "CC-0001",
        "name": 'ASUS ProArt Studiobook 16 OLED 16" 4K Creator Laptop (RTX 4070)',
        "price_cents": 249900,
        "specs": {
            "display": '16" OLED 4K (3840x2400) 120Hz 100% DCI-P3 PANTONE Validated',
            "display_inches": 16,
            "refresh_hz": 120,
            "cpu": "Intel Core i9-13980HX (24-core, up to 5.6GHz)",
            "ram_gb": 64,
            "storage_gb": 2000,
            "gpu": "NVIDIA GeForce RTX 4070 8GB GDDR6",
            "gpu_model": "RTX 4070",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Pro",
            "wifi": "Wi-Fi 6E",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 90,
            "weight_kg": 2.4,
            "ports": ["2x Thunderbolt 4", "2x USB-A 3.2", "HDMI 2.1", "SD card reader"],
            "use_case": "content_creator",
            "creator_features": ["4K OLED", "PANTONE validated", "Wacom pen support"],
            "rating": 4.8,
            "shipping_days": 3,
            "display_name": "ASUS ProArt Studiobook 16",
            "subtitle": "4K OLED | RTX 4070 | 64GB | Creator",
        },
    },
    {
        "sku": "CC-0002",
        "name": 'Dell XPS 15 9530 15.6" OLED Video Editing Creator Laptop (RTX 4060)',
        "price_cents": 199900,
        "specs": {
            "display": '15.6" OLED 3.5K (3456x2160) 120Hz 100% DCI-P3',
            "display_inches": 15.6,
            "refresh_hz": 120,
            "cpu": "Intel Core i9-13900H (14-core, up to 5.4GHz)",
            "ram_gb": 32,
            "storage_gb": 1000,
            "gpu": "NVIDIA GeForce RTX 4060 8GB GDDR6",
            "gpu_model": "RTX 4060",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Killer Wi-Fi 6E",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 86,
            "weight_kg": 1.86,
            "ports": ["2x Thunderbolt 4", "1x USB-A 3.1", "HDMI 2.1", "SD card reader"],
            "use_case": "content_creator",
            "creator_features": ["OLED display", "color accurate", "thunderbolt 4"],
            "rating": 4.7,
            "shipping_days": 2,
            "display_name": "Dell XPS 15",
            "subtitle": "3.5K OLED | RTX 4060 | 32GB | Creator",
        },
    },
    {
        "sku": "CC-0003",
        "name": 'HP ZBook Fury 16 G10 16" Mobile Workstation for Video Editing (RTX 3500 Ada)',
        "price_cents": 329900,
        "specs": {
            "display": '16" IPS 2560x1600 165Hz 100% DCI-P3 DreamColor',
            "display_inches": 16,
            "refresh_hz": 165,
            "cpu": "Intel Core i9-13950HX (24-core, up to 5.5GHz)",
            "ram_gb": 64,
            "storage_gb": 2000,
            "gpu": "NVIDIA RTX 3500 Ada 12GB GDDR6 ECC",
            "gpu_model": "RTX 3500 Ada",
            "gpu_vram_gb": 12,
            "os": "Windows 11 Pro",
            "wifi": "Wi-Fi 6E",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 99,
            "weight_kg": 3.0,
            "ports": ["2x Thunderbolt 4", "2x USB-A 3.2", "HDMI 2.1", "SD card reader", "RJ45"],
            "use_case": "content_creator",
            "creator_features": ["DreamColor display", "ECC VRAM", "workstation class"],
            "rating": 4.9,
            "shipping_days": 5,
            "display_name": "HP ZBook Fury 16",
            "subtitle": "RTX 3500 Ada | 64GB | DreamColor | Workstation",
        },
    },
    {
        "sku": "CC-0004",
        "name": 'Apple MacBook Pro 16-inch M3 Max 16" Content Creator Video Editing Laptop',
        "price_cents": 399900,
        "specs": {
            "display": '16.2" Liquid Retina XDR 3456x2234 120Hz 1600 nits HDR',
            "display_inches": 16.2,
            "refresh_hz": 120,
            "cpu": "Apple M3 Max (16-core CPU, 40-core GPU)",
            "ram_gb": 48,
            "storage_gb": 1000,
            "gpu": "Apple M3 Max 40-core GPU",
            "gpu_model": "Apple M3 Max GPU",
            "gpu_vram_gb": 48,
            "os": "macOS Sonoma",
            "wifi": "Wi-Fi 6E",
            "bluetooth": "Bluetooth 5.3",
            "battery_hours": 22,
            "weight_kg": 2.15,
            "ports": ["3x Thunderbolt 4", "HDMI 2.1", "SD card reader", "MagSafe 3"],
            "use_case": "content_creator",
            "creator_features": ["ProRes acceleration", "Liquid XDR", "industry standard for video"],
            "rating": 4.9,
            "shipping_days": 1,
            "display_name": "MacBook Pro 16 M3 Max",
            "subtitle": "M3 Max | 48GB | 1TB | ProRes | Content Creator",
        },
    },
    {
        "sku": "CC-0005",
        "name": 'Lenovo ThinkPad X1 Extreme Gen 6 16" 4K Creator Laptop (RTX 4070)',
        "price_cents": 279900,
        "specs": {
            "display": '16" IPS 4K (3840x2400) 120Hz 100% DCI-P3',
            "display_inches": 16,
            "refresh_hz": 120,
            "cpu": "Intel Core i9-13980HX (24-core, up to 5.6GHz)",
            "ram_gb": 32,
            "storage_gb": 1000,
            "gpu": "NVIDIA GeForce RTX 4070 8GB GDDR6",
            "gpu_model": "RTX 4070",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Pro",
            "wifi": "Wi-Fi 6E",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 90,
            "weight_kg": 1.8,
            "ports": ["2x Thunderbolt 4", "2x USB-A 3.2", "HDMI 2.1", "SD card reader"],
            "use_case": "content_creator",
            "creator_features": ["4K IPS", "Dolby Vision", "carbon fiber"],
            "rating": 4.7,
            "shipping_days": 3,
            "display_name": "Lenovo ThinkPad X1 Extreme Gen 6",
            "subtitle": "4K | RTX 4070 | 32GB | Creator Pro",
        },
    },
]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM products WHERE sku LIKE 'CC-%'")
    existing = cur.fetchone()[0]
    print(f"Existing content creator laptops (CC-*): {existing}")

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0

    for lap in CREATOR_LAPTOPS:
        cur.execute("SELECT sku FROM products WHERE sku = ?", (lap["sku"],))
        if cur.fetchone():
            print(f"  SKIP {lap['sku']} (already exists)")
            skipped += 1
            continue
        product_id = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                product_id,
                lap["sku"],
                lap["name"],
                lap["price_cents"],
                "USD",
                json.dumps(lap["specs"]),
                1,
                now,
            ),
        )
        inserted += 1
        print(f"  INS  {lap['sku']}  ${lap['price_cents'] // 100:,}  {lap['name'][:60]}")

    conn.commit()
    conn.close()
    print(f"\nDone: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    main()
