"""
Seed the demo SQLite catalog with real gaming laptops in the $1,199-$1,799 range.
These products are modelled on real 2024/2025 SKUs so the LLM has accurate specs to cite.
Run: python scripts/seed_gaming_laptops.py
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = "tmp/demo.sqlite"

GAMING_LAPTOPS = [
    {
        "sku": "GAM-0001",
        "name": 'ASUS ROG Strix G16 16" FHD 165Hz Gaming Laptop (RTX 4060)',
        "price_cents": 129900,
        "specs": {
            "display": '16" FHD (1920x1080) 165Hz IPS Anti-glare',
            "display_inches": 16,
            "refresh_hz": 165,
            "cpu": "Intel Core i7-13650HX (14-core, up to 4.9GHz)",
            "ram_gb": 16,
            "storage_gb": 512,
            "storage": "512GB PCIe NVMe SSD",
            "gpu": "NVIDIA GeForce RTX 4060 8GB GDDR6",
            "gpu_model": "RTX 4060",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 90,
            "weight_kg": 2.5,
            "ports": ["2x USB-A 3.2", "1x USB-C (USB4)", "HDMI 2.1", "SD card reader", "RJ45"],
            "gaming_style": True,
            "use_case": "gaming",
            "rating": 4.5,
            "shipping_days": 2,
            "display_name": "ASUS ROG Strix G16",
            "subtitle": "RTX 4060 | 16GB RAM | 165Hz",
        },
    },
    {
        "sku": "GAM-0002",
        "name": 'MSI Katana 15 B13VGK 15.6" FHD 144Hz Gaming Laptop (RTX 4070)',
        "price_cents": 149900,
        "specs": {
            "display": '15.6" FHD (1920x1080) 144Hz IPS',
            "display_inches": 15.6,
            "refresh_hz": 144,
            "cpu": "Intel Core i7-13620H (10-core, up to 4.9GHz)",
            "ram_gb": 16,
            "storage_gb": 1024,
            "storage": "1TB PCIe NVMe SSD",
            "gpu": "NVIDIA GeForce RTX 4070 8GB GDDR6",
            "gpu_model": "RTX 4070",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 86,
            "weight_kg": 2.1,
            "ports": ["3x USB-A 3.2", "1x USB-C", "HDMI 2.1", "SD card reader", "RJ45"],
            "gaming_style": True,
            "use_case": "gaming",
            "rating": 4.4,
            "shipping_days": 3,
            "display_name": "MSI Katana 15 B13VGK",
            "subtitle": "RTX 4070 | 16GB RAM | 144Hz",
        },
    },
    {
        "sku": "GAM-0003",
        "name": 'Lenovo LOQ 15IRH8 15.6" FHD 144Hz Gaming Laptop (RTX 4060)',
        "price_cents": 119900,
        "specs": {
            "display": '15.6" FHD (1920x1080) 144Hz IPS',
            "display_inches": 15.6,
            "refresh_hz": 144,
            "cpu": "Intel Core i7-13620H (10-core, up to 4.9GHz)",
            "ram_gb": 16,
            "storage_gb": 512,
            "storage": "512GB PCIe NVMe SSD",
            "gpu": "NVIDIA GeForce RTX 4060 8GB GDDR6",
            "gpu_model": "RTX 4060",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.1",
            "battery_wh": 60,
            "weight_kg": 2.4,
            "ports": ["2x USB-A 3.2", "1x USB-C", "HDMI 2.1", "RJ45"],
            "gaming_style": True,
            "use_case": "gaming",
            "rating": 4.3,
            "shipping_days": 3,
            "display_name": "Lenovo LOQ 15IRH8",
            "subtitle": "RTX 4060 | 16GB RAM | 144Hz",
        },
    },
    {
        "sku": "GAM-0004",
        "name": 'Acer Nitro 5 AN517-55 17.3" FHD 144Hz Gaming Laptop (RTX 4070)',
        "price_cents": 139900,
        "specs": {
            "display": '17.3" FHD (1920x1080) 144Hz IPS',
            "display_inches": 17.3,
            "refresh_hz": 144,
            "cpu": "Intel Core i7-12700H (14-core, up to 4.7GHz)",
            "ram_gb": 16,
            "storage_gb": 512,
            "storage": "512GB PCIe NVMe SSD",
            "gpu": "NVIDIA GeForce RTX 4070 8GB GDDR6",
            "gpu_model": "RTX 4070",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.2",
            "battery_wh": 90,
            "weight_kg": 2.9,
            "ports": ["2x USB-A 3.2", "1x USB-C", "HDMI 2.1", "SD card reader", "RJ45"],
            "gaming_style": True,
            "use_case": "gaming",
            "rating": 4.3,
            "shipping_days": 4,
            "display_name": "Acer Nitro 5 AN517-55",
            "subtitle": "RTX 4070 | 16GB RAM | 144Hz 17.3\"",
        },
    },
    {
        "sku": "GAM-0005",
        "name": 'HP Victus 16 16" FHD 144Hz Gaming Laptop (RTX 4060)',
        "price_cents": 124900,
        "specs": {
            "display": '16" FHD (1920x1080) 144Hz IPS',
            "display_inches": 16.1,
            "refresh_hz": 144,
            "cpu": "Intel Core i7-13700H (14-core, up to 5.0GHz)",
            "ram_gb": 16,
            "storage_gb": 512,
            "storage": "512GB PCIe NVMe SSD",
            "gpu": "NVIDIA GeForce RTX 4060 8GB GDDR6",
            "gpu_model": "RTX 4060",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 70,
            "weight_kg": 2.3,
            "ports": ["2x USB-A 3.2", "1x USB-C", "HDMI 2.1", "SD card reader", "RJ45"],
            "gaming_style": True,
            "use_case": "gaming",
            "rating": 4.2,
            "shipping_days": 2,
            "display_name": "HP Victus 16",
            "subtitle": "RTX 4060 | 16GB RAM | 144Hz",
        },
    },
    {
        "sku": "GAM-0006",
        "name": 'Dell G16 7630 16" QHD+ 240Hz Gaming Laptop (RTX 4070)',
        "price_cents": 169900,
        "specs": {
            "display": '16" QHD+ (2560x1600) 240Hz IPS',
            "display_inches": 16,
            "refresh_hz": 240,
            "cpu": "Intel Core i7-13650HX (14-core, up to 4.9GHz)",
            "ram_gb": 16,
            "storage_gb": 1024,
            "storage": "1TB PCIe NVMe SSD",
            "gpu": "NVIDIA GeForce RTX 4070 8GB GDDR6",
            "gpu_model": "RTX 4070",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 86,
            "weight_kg": 2.6,
            "ports": ["3x USB-A 3.2", "1x USB-C (Thunderbolt 4)", "HDMI 2.1", "SD card reader", "RJ45"],
            "gaming_style": True,
            "use_case": "gaming",
            "rating": 4.6,
            "shipping_days": 2,
            "display_name": "Dell G16 7630",
            "subtitle": "RTX 4070 | 16GB RAM | 240Hz QHD+",
        },
    },
    {
        "sku": "GAM-0007",
        "name": 'ASUS TUF Gaming A15 FA507NV 15.6" FHD 144Hz (RTX 4060, Ryzen 7)',
        "price_cents": 129900,
        "specs": {
            "display": '15.6" FHD (1920x1080) 144Hz IPS',
            "display_inches": 15.6,
            "refresh_hz": 144,
            "cpu": "AMD Ryzen 7 7745HX (8-core, up to 5.1GHz)",
            "ram_gb": 16,
            "storage_gb": 512,
            "storage": "512GB PCIe NVMe SSD",
            "gpu": "NVIDIA GeForce RTX 4060 8GB GDDR6",
            "gpu_model": "RTX 4060",
            "gpu_vram_gb": 8,
            "os": "Windows 11 Home",
            "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "battery_wh": 90,
            "weight_kg": 2.2,
            "ports": ["2x USB-A 3.2", "1x USB-C", "HDMI 2.1", "SD card reader", "RJ45"],
            "gaming_style": True,
            "use_case": "gaming",
            "rating": 4.5,
            "shipping_days": 2,
            "display_name": "ASUS TUF Gaming A15",
            "subtitle": "RTX 4060 | Ryzen 7 | 144Hz",
        },
    },
]


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Check current gaming laptop count
    cur.execute("SELECT COUNT(*) FROM products WHERE sku LIKE 'GAM-%'")
    existing = cur.fetchone()[0]
    print(f"Existing gaming laptops (GAM-*): {existing}")

    now = datetime.now(timezone.utc).isoformat()
    inserted = 0
    skipped = 0

    for lap in GAMING_LAPTOPS:
        cur.execute("SELECT sku FROM products WHERE sku = ?", (lap["sku"],))
        if cur.fetchone():
            print(f"  SKIP (exists): {lap['sku']} {lap['name'][:50]}")
            skipped += 1
            continue

        cur.execute(
            """INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at, image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                lap["sku"],
                lap["name"],
                lap["price_cents"],
                "USD",
                json.dumps(lap["specs"]),
                1,
                now,
                f"/static/images/{lap['sku']}.svg",
            ),
        )
        print(f"  INSERTED: {lap['sku']}  ${lap['price_cents']//100:,}  {lap['name'][:55]}")
        inserted += 1

    conn.commit()
    conn.close()

    print(f"\nDone. Inserted={inserted} Skipped={skipped}")
    print("Total gaming laptops now:")
    conn2 = sqlite3.connect(DB_PATH)
    cur2 = conn2.cursor()
    cur2.execute("SELECT sku, name, price_cents FROM products WHERE sku LIKE 'GAM-%' ORDER BY price_cents")
    for row in cur2.fetchall():
        print(f"  {row[0]}  ${row[2]//100:,}  {row[1][:60]}")
    conn2.close()


if __name__ == "__main__":
    main()
