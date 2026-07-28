"""
Seed the demo SQLite catalog with real products from docs/laptop-products-new-short.txt.
Covers laptops, gaming laptops, MacBooks, monitors, bags, tablets, routers, headsets,
printers and storage.

Run: python scripts/seed_real_catalog.py
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

DB_PATH = "tmp/demo.sqlite"
CATALOG_CURRENCY = str(os.getenv("CATALOG_SEED_CURRENCY") or "AUD").strip().upper()

# ---------------------------------------------------------------------------
# LAPTOPS — budget/mid-range (non-gaming, Windows/Copilot+)
# ---------------------------------------------------------------------------
LAPTOPS = [
    {
        "sku": "LAP-0001",
        "name": 'Dell 15 DC15255 15.6" FHD 120Hz Laptop (Ryzen 3) [512GB]',
        "price_cents": 62900,
        "specs": {
            "display": '15.6" FHD (1920x1080) 120Hz WVA',
            "display_inches": 15.6, "refresh_hz": 120,
            "cpu": "AMD Ryzen 3-7320U quad-core (up to 4.1GHz)",
            "ram_gb": 8, "storage_gb": 512, "storage": "512GB M.2 SSD",
            "gpu": "AMD Radeon 610M", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 5 (802.11ac)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB-A", "1x USB-C", "HDMI", "SD card reader"],
            "gaming_style": False, "use_case": "budget",
            "rating": 4.0, "shipping_days": 3,
            "display_name": "Dell 15 DC15255",
            "subtitle": "Ryzen 3 | 8GB RAM | 512GB",
        },
    },
    {
        "sku": "LAP-0002",
        "name": 'HP Laptop 15-fc0433AU 15.6" FHD Laptop (Ryzen 5) [512GB]',
        "price_cents": 64900,
        "specs": {
            "display": '15.6" FHD (1920x1080) SVA',
            "display_inches": 15.6, "refresh_hz": 60,
            "cpu": "AMD Ryzen 5-5625U 6-core (2.3GHz up to 4.3GHz)",
            "ram_gb": 8, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "AMD Radeon Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x USB-A", "1x USB-C", "HDMI"],
            "gaming_style": False, "use_case": "budget",
            "rating": 4.1, "shipping_days": 2,
            "display_name": "HP Laptop 15-fc0433AU",
            "subtitle": "Ryzen 5 | 8GB RAM | 512GB",
        },
    },
    {
        "sku": "LAP-0003",
        "name": 'Lenovo IdeaPad S3i 15.6" FHD Laptop (Intel Core i3) [512GB]',
        "price_cents": 69900,
        "specs": {
            "display": '15.6" FHD (1920x1080) TN',
            "display_inches": 15.6, "refresh_hz": 60,
            "cpu": "Intel Core i3-1315U 6-core (up to 4.5GHz)",
            "ram_gb": 8, "storage_gb": 512, "storage": "512GB M.2 SSD",
            "gpu": "Intel UHD Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.2",
            "ports": ["2x USB-A", "1x USB-C", "HDMI", "SD card reader"],
            "gaming_style": False, "use_case": "budget",
            "rating": 4.0, "shipping_days": 3,
            "display_name": "Lenovo IdeaPad S3i",
            "subtitle": "Core i3 | 8GB RAM | 512GB",
        },
    },
    {
        "sku": "LAP-0004",
        "name": 'HP Laptop 15-fc0474AU 15.6" FHD Laptop (Ryzen 7) [512GB]',
        "price_cents": 89900,
        "specs": {
            "display": '15.6" FHD (1920x1080) SVA',
            "display_inches": 15.6, "refresh_hz": 60,
            "cpu": "AMD Ryzen 7-5825U 8-core (2.0GHz up to 4.5GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "AMD Radeon Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x USB-A", "1x USB-C", "HDMI"],
            "gaming_style": False, "use_case": "everyday",
            "rating": 4.2, "shipping_days": 2,
            "display_name": "HP Laptop 15-fc0474AU",
            "subtitle": "Ryzen 7 | 16GB RAM | 512GB",
        },
    },
    {
        "sku": "LAP-0005",
        "name": 'ASUS VivoBook 15.6" FHD Thin & Light Laptop (Intel Core i5) [1TB]',
        "price_cents": 95900,
        "specs": {
            "display": '15.6" FHD (1920x1080) IPS',
            "display_inches": 15.6, "refresh_hz": 60,
            "cpu": "Intel Core i5-1334U 10-core (up to 4.6GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "Intel UHD Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["3x USB-A", "1x USB-C", "HDMI"],
            "gaming_style": False, "use_case": "everyday",
            "rating": 4.2, "shipping_days": 3,
            "display_name": "ASUS VivoBook 15",
            "subtitle": "Core i5 | 16GB RAM | 1TB",
        },
    },
    {
        "sku": "LAP-0006",
        "name": 'HP OmniBook 5 NG AI PC 14" WUXGA OLED Copilot+ PC (Snapdragon X1) [512GB]',
        "price_cents": 109900,
        "specs": {
            "display": '14" WUXGA (1920x1200) OLED',
            "display_inches": 14, "refresh_hz": 60,
            "cpu": "Qualcomm Snapdragon X1-26-100 8-core (up to 2.97GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "Qualcomm Adreno", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["1x USB-A", "2x USB-C"],
            "copilot_plus": True,
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.3, "shipping_days": 2,
            "display_name": "HP OmniBook 5 14\"",
            "subtitle": "Snapdragon X1 | 16GB RAM | OLED",
        },
    },
    {
        "sku": "LAP-0007",
        "name": 'Dell Inspiron 14 7440 14" WQXGA 2-in-1 Laptop (Intel Core i5) [512GB]',
        "price_cents": 119900,
        "specs": {
            "display": '14" WQXGA (1920x1200) Touch WVA',
            "display_inches": 14, "refresh_hz": 60,
            "cpu": "Intel Core i5-1334U 10-core (up to 4.6GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB M.2 SSD",
            "gpu": "Intel Iris Xe", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB 3.2", "2x USB-C", "HDMI", "SD card reader"],
            "form_factor": "2-in-1",
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.3, "shipping_days": 2,
            "display_name": "Dell Inspiron 14 7440 2-in-1",
            "subtitle": "Core i5 | 16GB RAM | Touch 2-in-1",
        },
    },
    {
        "sku": "LAP-0008",
        "name": 'Lenovo IdeaPad 5 14" 2K OLED 2-in-1 Copilot+ PC (Snapdragon X) [512GB]',
        "price_cents": 112400,
        "specs": {
            "display": '14" 2K (1920x1200) OLED Touch',
            "display_inches": 14, "refresh_hz": 60,
            "cpu": "Qualcomm Snapdragon X X1-26-100 8-core (up to 3.0GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB M.2 SSD",
            "gpu": "Qualcomm Adreno", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x USB-C", "2x USB-A", "HDMI", "microSD reader"],
            "form_factor": "2-in-1", "copilot_plus": True,
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.4, "shipping_days": 3,
            "display_name": "Lenovo IdeaPad 5 14\" OLED",
            "subtitle": "Snapdragon X | 16GB RAM | 2K OLED 2-in-1",
        },
    },
    {
        "sku": "LAP-0009",
        "name": 'Dell 15 DC15250 15.6" FHD 120Hz Laptop (Intel Core i5) [512GB]',
        "price_cents": 119900,
        "specs": {
            "display": '15.6" FHD (1920x1080) 120Hz WVA',
            "display_inches": 15.6, "refresh_hz": 120,
            "cpu": "Intel Core i5-1334U 10-core (up to 4.6GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB M.2 SSD",
            "gpu": "Intel UHD Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB-A", "1x USB-C", "HDMI", "SD card reader"],
            "gaming_style": False, "use_case": "everyday",
            "rating": 4.1, "shipping_days": 2,
            "display_name": "Dell 15 DC15250",
            "subtitle": "Core i5 | 16GB RAM | 120Hz",
        },
    },
    {
        "sku": "LAP-0010",
        "name": 'Dell DB16255 16" WUXGA Copilot+ PC Laptop (Ryzen AI 5) [512GB]',
        "price_cents": 125900,
        "specs": {
            "display": '16" WUXGA (1920x1200) LED',
            "display_inches": 16, "refresh_hz": 60,
            "cpu": "AMD Ryzen AI 5-340 6-core (up to 4.8GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB M.2 SSD",
            "gpu": "AMD Radeon Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["1x USB-A", "2x USB-C", "HDMI"],
            "copilot_plus": True,
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.2, "shipping_days": 3,
            "display_name": "Dell DB16255 (Ryzen AI 5)",
            "subtitle": "Ryzen AI 5 | 16GB RAM | Copilot+",
        },
    },
    {
        "sku": "LAP-0011",
        "name": 'Lenovo IdeaPad 5 14" OLED 2-in-1 Laptop (Snapdragon X Plus) [1TB]',
        "price_cents": 127400,
        "specs": {
            "display": '14" OLED (1920x1200) Touch',
            "display_inches": 14, "refresh_hz": 60,
            "cpu": "Qualcomm Snapdragon X Plus X1P-42-100 8-core (up to 3.4GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "Qualcomm Adreno", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB 3.2", "2x USB-C", "HDMI", "microSD reader"],
            "form_factor": "2-in-1",
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.3, "shipping_days": 3,
            "display_name": "Lenovo IdeaPad 5 14\" OLED 2-in-1",
            "subtitle": "Snapdragon X Plus | 16GB RAM | 1TB OLED",
        },
    },
    {
        "sku": "LAP-0012",
        "name": 'ASUS Vivobook S16 16" WQXGA Copilot+ PC Laptop (Snapdragon X) [512GB]',
        "price_cents": 127800,
        "specs": {
            "display": '16" WQXGA (2560x1600) IPS',
            "display_inches": 16, "refresh_hz": 60,
            "cpu": "Qualcomm Snapdragon X X1-26-100 8-core (2.97GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "Qualcomm Adreno", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB-C", "2x USB-A", "HDMI"],
            "copilot_plus": True,
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.3, "shipping_days": 2,
            "display_name": "ASUS Vivobook S16",
            "subtitle": "Snapdragon X | 16GB RAM | WQXGA",
        },
    },
    {
        "sku": "LAP-0013",
        "name": 'HP Envy x360 14" WUXGA 2-in-1 Laptop (Intel Core Ultra 5) [512GB]',
        "price_cents": 129900,
        "specs": {
            "display": '14" WUXGA (1920x1200) IPS Touch',
            "display_inches": 14, "refresh_hz": 60,
            "cpu": "Intel Core Ultra 5-125U 12-core (up to 4.3GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB M.2 SSD",
            "gpu": "Intel Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB-A", "1x USB-C", "1x Thunderbolt 4", "HDMI"],
            "form_factor": "2-in-1",
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.4, "shipping_days": 2,
            "display_name": "HP Envy x360 14\"",
            "subtitle": "Core Ultra 5 | 16GB RAM | Touch 2-in-1",
        },
    },
    {
        "sku": "LAP-0014",
        "name": "Microsoft Surface Pro 12\" Copilot+ PC (Snapdragon X Plus 8-core) [512GB/16GB]",
        "price_cents": 139900,
        "specs": {
            "display": '12" Copilot+ PC Touch display',
            "display_inches": 12, "refresh_hz": 120,
            "cpu": "Qualcomm Snapdragon X Plus 8-core",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "Qualcomm Adreno", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["USB-C"],
            "form_factor": "tablet", "copilot_plus": True,
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.3, "shipping_days": 3,
            "display_name": "Microsoft Surface Pro",
            "subtitle": "Snapdragon X Plus | 16GB RAM | Copilot+",
        },
    },
    {
        "sku": "LAP-0015",
        "name": 'Dell DB16255 16" WUXGA Copilot+ PC Laptop (Ryzen AI 7) [1TB]',
        "price_cents": 139900,
        "specs": {
            "display": '16" WUXGA (1920x1200) LED',
            "display_inches": 16, "refresh_hz": 60,
            "cpu": "AMD Ryzen AI 7-350 8-core (up to 5.0GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB M.2 SSD",
            "gpu": "AMD Radeon Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["1x USB-A", "2x USB-C", "HDMI"],
            "copilot_plus": True,
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.3, "shipping_days": 2,
            "display_name": "Dell DB16255 (Ryzen AI 7)",
            "subtitle": "Ryzen AI 7 | 16GB RAM | 1TB Copilot+",
        },
    },
    {
        "sku": "LAP-0016",
        "name": 'Lenovo Yoga Slim 7i Aura Edition 14" 2.8K OLED Laptop (Intel Core Ultra 5) [1TB]',
        "price_cents": 149900,
        "specs": {
            "display": '14" 2.8K (2880x1800) OLED',
            "display_inches": 14, "refresh_hz": 90,
            "cpu": "Intel Core Ultra 5 226V 8-core (up to 4.5GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "Intel Arc 130V", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x USB-C", "1x USB-A", "HDMI", "microSD reader"],
            "gaming_style": False, "use_case": "premium",
            "rating": 4.5, "shipping_days": 2,
            "display_name": "Lenovo Yoga Slim 7i Aura",
            "subtitle": "Core Ultra 5 | 16GB RAM | 2.8K OLED",
        },
    },
    {
        "sku": "LAP-0017",
        "name": 'MSI Modern 15 H AI 15.6" FHD Laptop (Intel Core Ultra 9) [1TB]',
        "price_cents": 149900,
        "specs": {
            "display": '15.6" FHD (1920x1080) IPS',
            "display_inches": 15.6, "refresh_hz": 60,
            "cpu": "Intel Core Ultra 9 285H 16-core (up to 5.4GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB M.2 SSD",
            "gpu": "Intel Arc Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["3x USB-A", "1x USB-C", "HDMI"],
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.3, "shipping_days": 3,
            "display_name": "MSI Modern 15 H AI (Ultra 9)",
            "subtitle": "Core Ultra 9 | 16GB RAM | 1TB",
        },
    },
    {
        "sku": "LAP-0018",
        "name": 'MSI Modern 15 H AI 15.6" FHD Laptop (Intel Core Ultra 7) [1TB]',
        "price_cents": 149900,
        "specs": {
            "display": '15.6" FHD (1920x1080) IPS',
            "display_inches": 15.6, "refresh_hz": 60,
            "cpu": "Intel Core Ultra 7 225H 16-core (up to 5.1GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB M.2 SSD",
            "gpu": "Intel Arc Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["3x USB-A", "1x USB-C", "HDMI"],
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.2, "shipping_days": 3,
            "display_name": "MSI Modern 15 H AI (Ultra 7)",
            "subtitle": "Core Ultra 7 | 16GB RAM | 1TB",
        },
    },
    {
        "sku": "LAP-0019",
        "name": 'Lenovo IdeaPad Slim 3i 15.3" 2K Laptop (Intel Core i7) [1TB]',
        "price_cents": 159900,
        "specs": {
            "display": '15.3" 2K (1920x1200) IPS',
            "display_inches": 15.3, "refresh_hz": 60,
            "cpu": "Intel Core i7-13620H 10-core (up to 4.9GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB M.2 SSD",
            "gpu": "Intel UHD Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.2",
            "ports": ["2x USB-A", "1x USB-C", "HDMI", "SD card reader"],
            "gaming_style": False, "use_case": "productivity",
            "rating": 4.2, "shipping_days": 3,
            "display_name": "Lenovo IdeaPad Slim 3i",
            "subtitle": "Core i7 | 16GB RAM | 2K 1TB",
        },
    },
    {
        "sku": "LAP-0020",
        "name": 'MSI Prestige A16 AI+ 16" UHD+ OLED Laptop (Ryzen 9) [1TB]',
        "price_cents": 309900,
        "specs": {
            "display": '16" UHD+ (3840x2400) IPS',
            "display_inches": 16, "refresh_hz": 60,
            "cpu": "AMD Ryzen 9 AI 365 10-core (up to 5.0GHz)",
            "ram_gb": 32, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "AMD Radeon Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["1x USB 3.2", "2x USB-C", "HDMI", "microSD reader"],
            "gaming_style": False, "use_case": "premium",
            "rating": 4.5, "shipping_days": 2,
            "display_name": "MSI Prestige A16 AI+",
            "subtitle": "Ryzen 9 AI | 32GB RAM | UHD+ OLED",
        },
    },
    {
        "sku": "LAP-0021",
        "name": 'HP OmniBook Ultra 14" 2.2K Laptop (Ryzen 9 AI HX 375) [1TB]',
        "price_cents": 369900,
        "specs": {
            "display": '14" WQXGA (2240x1400) IPS Touchscreen',
            "display_inches": 14, "refresh_hz": 60,
            "cpu": "AMD Ryzen 9 AI 9 HX 375 12-core (up to 5.1GHz)",
            "ram_gb": 32, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "AMD Radeon Graphics", "gpu_model": None, "gpu_vram_gb": None,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x Thunderbolt 4"],
            "gaming_style": False, "use_case": "premium",
            "rating": 4.6, "shipping_days": 2,
            "display_name": "HP OmniBook Ultra 14\"",
            "subtitle": "Ryzen 9 AI | 32GB RAM | Touchscreen",
        },
    },
]

# ---------------------------------------------------------------------------
# GAMING LAPTOPS — real products from catalog
# ---------------------------------------------------------------------------
GAMING_LAPTOPS_REAL = [
    {
        "sku": "RGAM-0001",
        "name": 'MSI Thin A15 15.6" FHD 144Hz Gaming Laptop (Ryzen 5) [GeForce RTX 3050]',
        "price_cents": 179900,
        "specs": {
            "display": '15.6" FHD (1920x1080) 144Hz IPS',
            "display_inches": 15.6, "refresh_hz": 144,
            "cpu": "AMD Ryzen 5-7535HS 6-core (3.3-4.55GHz)",
            "ram_gb": 8, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "NVIDIA GeForce RTX 3050 4GB GDDR6",
            "gpu_model": "RTX 3050", "gpu_vram_gb": 4,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["3x USB 3.2", "1x USB-C", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.2, "shipping_days": 3,
            "display_name": "MSI Thin A15",
            "subtitle": "RTX 3050 | Ryzen 5 | 144Hz",
        },
    },
    {
        "sku": "RGAM-0002",
        "name": 'HP Victus 15-fa2364TX 15.6" FHD Gaming Laptop (Intel Core i7) [GeForce RTX 4050]',
        "price_cents": 189900,
        "specs": {
            "display": '15.6" FHD (1920x1080) IPS',
            "display_inches": 15.6, "refresh_hz": 144,
            "cpu": "Intel Core i7-13620H 10-core (up to 4.9GHz)",
            "ram_gb": 16, "storage_gb": 256, "storage": "256GB M.2 SSD",
            "gpu": "NVIDIA GeForce RTX 4050 6GB GDDR6",
            "gpu_model": "RTX 4050", "gpu_vram_gb": 6,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x USB-A", "1x USB-C", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.3, "shipping_days": 2,
            "display_name": "HP Victus 15-fa2364TX",
            "subtitle": "RTX 4050 | Core i7 | 16GB RAM",
        },
    },
    {
        "sku": "RGAM-0003",
        "name": 'ASUS TUF Gaming F16 16" FHD+ 144Hz Gaming Laptop (Core i7) [GeForce RTX 4050]',
        "price_cents": 191900,
        "specs": {
            "display": '16" FHD+ (1920x1200) 144Hz IPS',
            "display_inches": 16, "refresh_hz": 144,
            "cpu": "Intel Core i7-13620H 10-core (up to 4.9GHz)",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "NVIDIA GeForce RTX 4050 6GB GDDR6",
            "gpu_model": "RTX 4050", "gpu_vram_gb": 6,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6 (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB 3.2", "1x USB-C 3.2", "1x Thunderbolt 4", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.5, "shipping_days": 2,
            "display_name": "ASUS TUF Gaming F16",
            "subtitle": "RTX 4050 | Core i7 | 16\" 144Hz",
        },
    },
    {
        "sku": "RGAM-0004",
        "name": 'ASUS TUF F16 16" FHD+ 165Hz Gaming Laptop (Core i7) [GeForce RTX 5060 8GB]',
        "price_cents": 289900,
        "specs": {
            "display": '16" WUXGA (2560x1600) 165Hz IPS',
            "display_inches": 16, "refresh_hz": 165,
            "cpu": "Intel Core i7-14650HX 16-core (up to 5.2GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "NVIDIA GeForce RTX 5060 8GB GDDR7",
            "gpu_model": "RTX 5060", "gpu_vram_gb": 8,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["2x USB-A", "1x USB-C", "1x Thunderbolt 4", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.6, "shipping_days": 2,
            "display_name": "ASUS TUF F16 RTX 5060",
            "subtitle": "RTX 5060 8GB GDDR7 | Core i7 | 165Hz",
        },
    },
    {
        "sku": "RGAM-0005",
        "name": 'Alienware 16 Aurora 16" WQXGA 120Hz Gaming Laptop (Core 7) [GeForce RTX 5060]',
        "price_cents": 349900,
        "specs": {
            "display": '16" WQXGA (2560x1600) 120Hz',
            "display_inches": 16, "refresh_hz": 120,
            "cpu": "Intel Core 7 240H 10-core (up to 5.2GHz)",
            "ram_gb": 32, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "NVIDIA GeForce RTX 5060 8GB GDDR6",
            "gpu_model": "RTX 5060", "gpu_vram_gb": 8,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x USB-C", "2x USB-A", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.6, "shipping_days": 2,
            "display_name": "Alienware 16 Aurora",
            "subtitle": "RTX 5060 | 32GB RAM | Core 7",
        },
    },
    {
        "sku": "RGAM-0006",
        "name": 'Alienware 16X Aurora 16" WQXGA 240Hz Gaming Laptop (Core Ultra 7) [GeForce RTX 5060]',
        "price_cents": 389900,
        "specs": {
            "display": '16" WQXGA (2560x1600) 240Hz',
            "display_inches": 16, "refresh_hz": 240,
            "cpu": "Intel Core Ultra 7 255HX 12-core (up to 5.2GHz)",
            "ram_gb": 16, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "NVIDIA GeForce RTX 5060 8GB GDDR6",
            "gpu_model": "RTX 5060", "gpu_vram_gb": 8,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["2x USB-C", "2x USB-A", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.7, "shipping_days": 2,
            "display_name": "Alienware 16X Aurora",
            "subtitle": "RTX 5060 | Core Ultra 7 | 240Hz",
        },
    },
    {
        "sku": "RGAM-0007",
        "name": 'HP OMEN MAX 16" 2.5K 240Hz OLED Gaming Laptop (Core Ultra 9) [GeForce RTX 5080]',
        "price_cents": 449900,
        "specs": {
            "display": '16" 2.5K (2560x1600) 240Hz OLED',
            "display_inches": 16, "refresh_hz": 240,
            "cpu": "Intel Core Ultra 9 275HX 24-core (up to 5.4GHz)",
            "ram_gb": 32, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "NVIDIA GeForce RTX 5080 16GB GDDR7",
            "gpu_model": "RTX 5080", "gpu_vram_gb": 16,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["1x USB-A", "2x Thunderbolt 4", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.8, "shipping_days": 3,
            "display_name": "HP OMEN MAX 16\"",
            "subtitle": "RTX 5080 16GB | Core Ultra 9 | 240Hz OLED",
        },
    },
    {
        "sku": "RGAM-0008",
        "name": 'Lenovo Legion Pro 7 16" WQXGA 240Hz OLED Gaming Laptop (Core Ultra 9) [RTX 5090]',
        "price_cents": 599900,
        "specs": {
            "display": '16" WQXGA (2560x1600) 240Hz OLED',
            "display_inches": 16, "refresh_hz": 240,
            "cpu": "Intel Core Ultra 9-275HX 24-core (up to 5.4GHz)",
            "ram_gb": 64, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "NVIDIA GeForce RTX 5090 24GB GDDR7",
            "gpu_model": "RTX 5090", "gpu_vram_gb": 24,
            "os": "Windows 11 Home", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 5.4",
            "ports": ["3x USB 3.2", "1x USB-C", "1x Thunderbolt 4", "HDMI"],
            "gaming_style": True, "use_case": "gaming",
            "rating": 4.9, "shipping_days": 2,
            "display_name": "Lenovo Legion Pro 7",
            "subtitle": "RTX 5090 24GB | 64GB RAM | 240Hz OLED",
        },
    },
]

# ---------------------------------------------------------------------------
# APPLE PRODUCTS
# ---------------------------------------------------------------------------
APPLE_PRODUCTS = [
    {
        "sku": "MAC-0001",
        "name": "Apple MacBook Neo 13-inch A18 Pro 256GB/8GB (Indigo)",
        "price_cents": 89900,
        "specs": {
            "display": '13" Liquid Retina (2408x1506)',
            "display_inches": 13, "refresh_hz": 60,
            "cpu": "Apple A18 Pro 6-core",
            "ram_gb": 8, "storage_gb": 256, "storage": "256GB SSD",
            "gpu": "Apple GPU 5-core", "gpu_model": None, "gpu_vram_gb": None,
            "os": "macOS", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 6.0",
            "ports": ["2x USB-C"],
            "battery_hours": 16, "colour": "Indigo",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "everyday",
            "rating": 4.6, "shipping_days": 2,
            "display_name": "Apple MacBook Neo 13\" (Indigo)",
            "subtitle": "A18 Pro | 8GB RAM | 256GB",
        },
    },
    {
        "sku": "MAC-0002",
        "name": "Apple MacBook Neo 13-inch A18 Pro 512GB/8GB (Blush)",
        "price_cents": 109900,
        "specs": {
            "display": '13" Liquid Retina (2408x1506)',
            "display_inches": 13, "refresh_hz": 60,
            "cpu": "Apple A18 Pro 6-core",
            "ram_gb": 8, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "Apple GPU 5-core", "gpu_model": None, "gpu_vram_gb": None,
            "os": "macOS", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 6.0",
            "ports": ["2x USB-C"],
            "battery_hours": 16, "colour": "Blush",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "everyday",
            "rating": 4.6, "shipping_days": 2,
            "display_name": "Apple MacBook Neo 13\" (Blush)",
            "subtitle": "A18 Pro | 8GB RAM | 512GB",
        },
    },
    {
        "sku": "MAC-0003",
        "name": "Apple MacBook Neo 13-inch A18 Pro 256GB/8GB (Silver)",
        "price_cents": 89900,
        "specs": {
            "display": '13" Liquid Retina (2408x1506)',
            "display_inches": 13, "refresh_hz": 60,
            "cpu": "Apple A18 Pro 6-core",
            "ram_gb": 8, "storage_gb": 256, "storage": "256GB SSD",
            "gpu": "Apple GPU 5-core", "gpu_model": None, "gpu_vram_gb": None,
            "os": "macOS", "wifi": "Wi-Fi 6E (802.11ax)",
            "bluetooth": "Bluetooth 6.0",
            "ports": ["2x USB-C"],
            "battery_hours": 16, "colour": "Silver",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "everyday",
            "rating": 4.6, "shipping_days": 2,
            "display_name": "Apple MacBook Neo 13\" (Silver)",
            "subtitle": "A18 Pro | 8GB RAM | 256GB",
        },
    },
    {
        "sku": "MAC-0004",
        "name": "Apple MacBook Air 13-inch M5 512GB/16GB (Midnight)",
        "price_cents": 179900,
        "specs": {
            "display": '13.6" Liquid Retina (2560x1664)',
            "display_inches": 13.6, "refresh_hz": 60,
            "cpu": "Apple M5 10-core",
            "ram_gb": 16, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "Apple GPU 8-core", "gpu_model": None, "gpu_vram_gb": None,
            "os": "macOS", "wifi": "Wi-Fi 7 (802.11be)",
            "bluetooth": "Bluetooth 6.0",
            "ports": ["2x Thunderbolt 4", "MagSafe 3"],
            "battery_hours": 18, "colour": "Midnight",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "premium",
            "rating": 4.8, "shipping_days": 2,
            "display_name": "Apple MacBook Air 13\" M5",
            "subtitle": "Apple M5 | 16GB RAM | Wi-Fi 7",
        },
    },
    {
        "sku": "MAC-0005",
        "name": "Apple MacBook Pro 14-inch M4 1TB/24GB (Silver) [2024]",
        "price_cents": 288700,
        "specs": {
            "display": '14" Liquid Retina XDR',
            "display_inches": 14, "refresh_hz": 120,
            "cpu": "Apple M4 chip",
            "ram_gb": 24, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "Apple GPU", "gpu_model": None, "gpu_vram_gb": None,
            "graphics_architecture": "unified",
            "graphics_memory_model": "unified_memory", "unified_memory_gb": 24,
            "native_metal": True,
            "graphics_capability_source": "https://support.apple.com/en-us/121552",
            "os": "macOS", "wifi": "Wi-Fi 6E",
            "bluetooth": "Bluetooth 5.3",
            "ports": ["3x Thunderbolt 4", "HDMI", "SD card reader", "MagSafe 3"],
            "colour": "Silver",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "premium",
            "rating": 4.8, "shipping_days": 2,
            "display_name": "Apple MacBook Pro 14\" M4",
            "subtitle": "Apple M4 | 24GB RAM | 1TB",
        },
    },
    {
        "sku": "MAC-0006",
        "name": "Apple iMac 24-inch M4 512GB/24GB (Silver) [2024]",
        "price_cents": 288700,
        "specs": {
            "display": '24" 4.5K Retina (4480x2520)',
            "display_inches": 24, "refresh_hz": 60,
            "cpu": "Apple M4 10-core",
            "ram_gb": 24, "storage_gb": 512, "storage": "512GB SSD",
            "gpu": "Apple GPU", "gpu_model": None, "gpu_vram_gb": None,
            "graphics_architecture": "unified",
            "graphics_memory_model": "unified_memory", "unified_memory_gb": 24,
            "native_metal": True,
            "graphics_capability_source": "https://support.apple.com/en-us/121557",
            "os": "macOS",
            "form_factor": "desktop", "colour": "Silver",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "desktop",
            "rating": 4.8, "shipping_days": 3,
            "display_name": "Apple iMac 24\" M4",
            "subtitle": "Apple M4 | 24GB RAM | 4.5K Display",
        },
    },
    {
        "sku": "MAC-0007",
        "name": "Apple MacBook Pro 14-inch M5 1TB/24GB (Space Black)",
        "price_cents": 309900,
        "specs": {
            "display": '14" Liquid Retina XDR',
            "display_inches": 14, "refresh_hz": 120,
            "cpu": "Apple M5 chip",
            "ram_gb": 24, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "Apple GPU", "gpu_model": None, "gpu_vram_gb": None,
            "graphics_architecture": "unified",
            "graphics_memory_model": "unified_memory", "unified_memory_gb": 24,
            "native_metal": True,
            "graphics_capability_source": "https://support.apple.com/en-us/125405",
            "os": "macOS",
            "colour": "Space Black",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "premium",
            "rating": 4.9, "shipping_days": 2,
            "display_name": "Apple MacBook Pro 14\" M5",
            "subtitle": "Apple M5 | 24GB RAM | 1TB",
        },
    },
    {
        "sku": "MAC-0008",
        "name": "Apple MacBook Pro 14-inch M4 Pro 1TB/24GB (Space Black) [2024]",
        "price_cents": 389900,
        "specs": {
            "display": '14" Liquid Retina XDR',
            "display_inches": 14, "refresh_hz": 120,
            "cpu": "Apple M4 Pro chip",
            "ram_gb": 24, "storage_gb": 1024, "storage": "1TB SSD",
            "gpu": "Apple GPU", "gpu_model": None, "gpu_vram_gb": None,
            "graphics_architecture": "unified",
            "graphics_memory_model": "unified_memory", "unified_memory_gb": 24,
            "native_metal": True,
            "graphics_capability_source": "https://support.apple.com/en-us/121553",
            "os": "macOS",
            "colour": "Space Black",
            "apple_intelligence": True,
            "gaming_style": False, "use_case": "premium",
            "rating": 4.9, "shipping_days": 2,
            "display_name": "Apple MacBook Pro 14\" M4 Pro",
            "subtitle": "Apple M4 Pro | 24GB RAM | 1TB",
        },
    },
]

# ---------------------------------------------------------------------------
# MONITORS
# ---------------------------------------------------------------------------
MONITORS = [
    {
        "sku": "MON-0001",
        "name": 'LG UltraGear 24G411A 24" FHD 144Hz Gaming Monitor',
        "price_cents": 18900,
        "specs": {
            "display": '24" FHD (1920x1080) IPS', "display_inches": 24,
            "refresh_hz": 144, "response_ms": 1,
            "g_sync": True, "freesync": True, "hdr": "HDR10",
            "use_case": "gaming", "rating": 4.4, "shipping_days": 2,
            "display_name": "LG UltraGear 24G411A 24\"",
            "subtitle": "24\" FHD | 144Hz | G-Sync Compatible",
        },
    },
    {
        "sku": "MON-0002",
        "name": 'AOC 16T20 15.6" FHD USB-C Portable Monitor',
        "price_cents": 17900,
        "specs": {
            "display": '15.6" FHD (1920x1080) IPS Portable', "display_inches": 15.6,
            "refresh_hz": 60, "response_ms": 20, "portable": True,
            "use_case": "everyday", "rating": 4.2, "shipping_days": 2,
            "display_name": "AOC 16T20 Portable 15.6\"",
            "subtitle": "15.6\" FHD Portable | USB-C",
        },
    },
    {
        "sku": "MON-0003",
        "name": 'LG UltraGear 27G411A 27" FHD 144Hz Gaming Monitor',
        "price_cents": 22900,
        "specs": {
            "display": '27" FHD (1920x1080) IPS', "display_inches": 27,
            "refresh_hz": 144, "response_ms": 1,
            "g_sync": True, "freesync": True, "hdr": "HDR10",
            "use_case": "gaming", "rating": 4.5, "shipping_days": 2,
            "display_name": "LG UltraGear 27G411A 27\"",
            "subtitle": "27\" FHD | 144Hz | G-Sync Compatible",
        },
    },
    {
        "sku": "MON-0004",
        "name": 'AOC C27G4Z 27" FHD 280Hz Curved Gaming Monitor',
        "price_cents": 33900,
        "specs": {
            "display": '27" FHD (1920x1080) Curved VA', "display_inches": 27,
            "refresh_hz": 280, "response_ms": 0.3, "curved": True,
            "freesync": True, "hdr": "HDR10",
            "use_case": "gaming", "rating": 4.4, "shipping_days": 3,
            "display_name": "AOC C27G4Z 27\" 280Hz",
            "subtitle": "27\" FHD Curved | 280Hz | 0.3ms",
        },
    },
    {
        "sku": "MON-0005",
        "name": 'Blaupunkt BP27GM240 27" FHD 240Hz Curved Gaming Monitor',
        "price_cents": 39900,
        "specs": {
            "display": '27" FHD (1920x1080) Curved', "display_inches": 27,
            "refresh_hz": 240, "response_ms": 3, "curved": True,
            "use_case": "gaming", "rating": 4.1, "shipping_days": 3,
            "display_name": "Blaupunkt BP27GM240",
            "subtitle": "27\" FHD Curved | 240Hz",
        },
    },
    {
        "sku": "MON-0006",
        "name": 'LG 31.5" QHD 100Hz IPS Super Slim Stand Monitor with USB-C',
        "price_cents": 38900,
        "specs": {
            "display": '31.5" QHD (2560x1440) IPS', "display_inches": 31.5,
            "refresh_hz": 100, "response_ms": 5,
            "use_case": "productivity", "rating": 4.3, "shipping_days": 3,
            "display_name": "LG 31.5\" QHD 100Hz",
            "subtitle": "31.5\" QHD | 100Hz | USB-C",
        },
    },
    {
        "sku": "MON-0007",
        "name": 'Lenovo Legion R34w-30 34" WQHD 180Hz Curved Gaming Monitor',
        "price_cents": 49900,
        "specs": {
            "display": '34" WQHD (3440x1440) VA Curved', "display_inches": 34,
            "refresh_hz": 180, "response_ms": 0.5, "curved": True,
            "hdr": "HDR10",
            "use_case": "gaming", "rating": 4.5, "shipping_days": 2,
            "display_name": "Lenovo Legion R34w-30",
            "subtitle": "34\" WQHD Curved | 180Hz | 0.5ms",
        },
    },
    {
        "sku": "MON-0008",
        "name": 'LG UltraGear 34G600A 34" WQHD 160Hz Curved Gaming Monitor',
        "price_cents": 69900,
        "specs": {
            "display": '34" WQHD (3440x1440) VA Curved', "display_inches": 34,
            "refresh_hz": 160, "response_ms": 1, "curved": True,
            "freesync": True,
            "use_case": "gaming", "rating": 4.5, "shipping_days": 2,
            "display_name": "LG UltraGear 34G600A",
            "subtitle": "34\" WQHD Curved | 160Hz | FreeSync",
        },
    },
    {
        "sku": "MON-0009",
        "name": 'Samsung Odyssey G91SD 49" DQHD 144Hz OLED Curved Gaming Monitor',
        "price_cents": 199900,
        "specs": {
            "display": '49" DQHD (5120x1440) OLED Curved', "display_inches": 49,
            "refresh_hz": 144, "response_ms": 0.03, "curved": True,
            "freesync": True, "hdr": "VESA DisplayHDR True Black 400",
            "use_case": "gaming", "rating": 4.7, "shipping_days": 5,
            "display_name": "Samsung Odyssey G91SD 49\" OLED",
            "subtitle": "49\" DQHD OLED | 144Hz | 0.03ms",
        },
    },
    {
        "sku": "MON-0010",
        "name": 'ASUS ROG Strix XG32UCWMG 32" 4K 240Hz OLED Gaming Monitor',
        "price_cents": 199900,
        "specs": {
            "display": '32" 4K UHD (3840x2160) OLED', "display_inches": 32,
            "refresh_hz": 240, "response_ms": 0.03,
            "g_sync": True, "hdr": "HDR",
            "use_case": "gaming", "rating": 4.8, "shipping_days": 3,
            "display_name": "ASUS ROG Strix XG32UCWMG",
            "subtitle": "32\" 4K OLED | 240Hz | G-Sync",
        },
    },
]

# ---------------------------------------------------------------------------
# BAGS / CASES
# ---------------------------------------------------------------------------
BAGS = [
    {
        "sku": "BAG-0001",
        "name": 'STM Tower View Folio 18" Laptop Brief (Black)',
        "price_cents": 6995,
        "specs": {
            "fits_inches": 18, "colour": "Black",
            "use_case": "bag", "rating": 4.2, "shipping_days": 3,
            "display_name": "STM Tower View Folio 18\"",
            "subtitle": "Fits up to 18\" laptops",
        },
    },
    {
        "sku": "BAG-0002",
        "name": 'Generation Earth 14.1" Recycled Berlin Laptop Backpack (Black)',
        "price_cents": 7900,
        "specs": {
            "fits_inches": 14.1, "colour": "Black", "eco_friendly": True,
            "use_case": "bag", "rating": 4.4, "shipping_days": 2,
            "display_name": "Generation Earth Berlin Backpack 14.1\"",
            "subtitle": "Eco recycled | Fits 14.1\" laptop",
        },
    },
    {
        "sku": "BAG-0003",
        "name": 'Thule Gauntlet MacBook Pro Attache 14" (Black)',
        "price_cents": 17995,
        "specs": {
            "fits_inches": 14, "colour": "Black", "brand": "Thule",
            "use_case": "bag", "rating": 4.6, "shipping_days": 2,
            "display_name": "Thule Gauntlet 14\" Attache",
            "subtitle": "Fits 14\" MacBook Pro | Rigid protection",
        },
    },
    {
        "sku": "BAG-0004",
        "name": 'Lenovo Legion GB800 17" Gaming Laptop Backpack (Black)',
        "price_cents": 19900,
        "specs": {
            "fits_inches": 17, "colour": "Black", "gaming_style": True,
            "use_case": "bag", "rating": 4.5, "shipping_days": 2,
            "display_name": "Lenovo Legion GB800 17\" Backpack",
            "subtitle": "Gaming backpack | Fits 17\" laptop",
        },
    },
]

# ---------------------------------------------------------------------------
# TABLETS
# ---------------------------------------------------------------------------
TABLETS = [
    {
        "sku": "TAB-0001",
        "name": "Lenovo Tab 10\" WUXGA 128GB Tablet with Clear Case",
        "price_cents": 29900,
        "specs": {
            "display": '10.1" WUXGA (1920x1200)', "display_inches": 10.1,
            "cpu": "MediaTek Helio G85 Octa-core",
            "ram_gb": 4, "storage_gb": 128, "os": "Android",
            "wifi": "Wi-Fi 5 (802.11ac)", "bluetooth": "Bluetooth 5.3",
            "use_case": "tablet", "rating": 4.1, "shipping_days": 3,
            "display_name": "Lenovo Tab 10\" WUXGA",
            "subtitle": "10\" Android | 128GB | MediaTek",
        },
    },
    {
        "sku": "TAB-0002",
        "name": "Samsung Galaxy Tab A11+ 11\" Wi-Fi 128GB (Grey)",
        "price_cents": 37900,
        "specs": {
            "display": '11" WUXGA (1920x1200)', "display_inches": 11,
            "cpu": "MTK Octa-core (up to 2.5GHz)",
            "ram_gb": 6, "storage_gb": 128, "os": "Android",
            "wifi": "Wi-Fi 5 (802.11ac)", "bluetooth": "Bluetooth 5.3",
            "use_case": "tablet", "rating": 4.2, "shipping_days": 2,
            "display_name": "Samsung Galaxy Tab A11+ 11\" Wi-Fi",
            "subtitle": "11\" Android | 128GB | Wi-Fi",
        },
    },
    {
        "sku": "TAB-0003",
        "name": "Apple iPad 11-inch A16 128GB Wi-Fi (Blue)",
        "price_cents": 49900,
        "specs": {
            "display": '11" Liquid Retina (2360x1640)', "display_inches": 11,
            "cpu": "Apple A16 5-core",
            "ram_gb": 8, "storage_gb": 128, "os": "iPadOS 18",
            "wifi": "Wi-Fi 6 (802.11ax)", "bluetooth": "Bluetooth 5.3",
            "colour": "Blue",
            "use_case": "tablet", "rating": 4.6, "shipping_days": 2,
            "display_name": "Apple iPad 11\" A16",
            "subtitle": "11\" iPad | A16 Chip | 128GB",
        },
    },
    {
        "sku": "TAB-0004",
        "name": "Samsung Galaxy Tab A11+ 11\" 5G 128GB (Grey)",
        "price_cents": 52900,
        "specs": {
            "display": '11" WUXGA (1920x1200)', "display_inches": 11,
            "cpu": "MTK Octa-core (up to 2.5GHz)",
            "ram_gb": 6, "storage_gb": 128, "os": "Android",
            "wifi": "Wi-Fi 5 (802.11ac)", "bluetooth": "Bluetooth 5.3",
            "connectivity": "5G",
            "use_case": "tablet", "rating": 4.2, "shipping_days": 2,
            "display_name": "Samsung Galaxy Tab A11+ 11\" 5G",
            "subtitle": "11\" Android | 128GB | 5G",
        },
    },
    {
        "sku": "TAB-0005",
        "name": "Samsung Galaxy Tab S10 FE+ 13.1\" Wi-Fi 128GB (Grey)",
        "price_cents": 109900,
        "specs": {
            "display": '13.1" WQXGA+ (2880x1800)', "display_inches": 13.1,
            "cpu": "Samsung Exynos 1580 Octa-core (up to 2.9GHz)",
            "ram_gb": 8, "storage_gb": 128, "os": "Android",
            "wifi": "Wi-Fi 6 (802.11ax)", "bluetooth": "Bluetooth 5.3",
            "use_case": "tablet", "rating": 4.4, "shipping_days": 2,
            "display_name": "Samsung Galaxy Tab S10 FE+ 13.1\"",
            "subtitle": "13.1\" Android | 128GB | Wi-Fi 6",
        },
    },
    {
        "sku": "TAB-0006",
        "name": "Apple iPad Air 13-inch M3 128GB Wi-Fi (Space Grey)",
        "price_cents": 134700,
        "specs": {
            "display": '13" Liquid Retina (2732x2048)', "display_inches": 13,
            "cpu": "Apple M3 8-core",
            "ram_gb": 8, "storage_gb": 128, "os": "iPadOS 18",
            "wifi": "Wi-Fi 6E (802.11ax)", "bluetooth": "Bluetooth 5.3",
            "colour": "Space Grey",
            "apple_intelligence": True,
            "use_case": "tablet", "rating": 4.7, "shipping_days": 2,
            "display_name": "Apple iPad Air 13\" M3",
            "subtitle": "13\" iPad Air | M3 Chip | Apple Intelligence",
        },
    },
]

# ---------------------------------------------------------------------------
# NETWORKING
# ---------------------------------------------------------------------------
NETWORKING = [
    {
        "sku": "NET-0001",
        "name": "TP-Link AC750 Wi-Fi Range Extender",
        "price_cents": 5900,
        "specs": {
            "wifi_standard": "Wi-Fi 5 (802.11ac)", "speed_mbps": 750,
            "use_case": "networking", "rating": 4.0, "shipping_days": 3,
            "display_name": "TP-Link AC750 Range Extender",
            "subtitle": "Wi-Fi 5 | AC750",
        },
    },
    {
        "sku": "NET-0002",
        "name": "Netgear Nighthawk Wi-Fi 6 AX1800 Router RAX9",
        "price_cents": 14900,
        "specs": {
            "wifi_standard": "Wi-Fi 6 (802.11ax)", "speed_mbps": 1800,
            "use_case": "networking", "rating": 4.3, "shipping_days": 2,
            "display_name": "Netgear Nighthawk AX1800",
            "subtitle": "Wi-Fi 6 | AX1800",
        },
    },
    {
        "sku": "NET-0003",
        "name": "TP-Link AX3000 Mesh Wi-Fi 6 Range Extender",
        "price_cents": 14900,
        "specs": {
            "wifi_standard": "Wi-Fi 6 (802.11ax)", "speed_mbps": 3000,
            "use_case": "networking", "rating": 4.3, "shipping_days": 2,
            "display_name": "TP-Link AX3000 Mesh Extender",
            "subtitle": "Wi-Fi 6 | AX3000 Mesh",
        },
    },
    {
        "sku": "NET-0004",
        "name": "TP-Link AX3000 Gigabit Wi-Fi 6 Router",
        "price_cents": 15900,
        "specs": {
            "wifi_standard": "Wi-Fi 6 (802.11ax)", "speed_mbps": 3000,
            "use_case": "networking", "rating": 4.4, "shipping_days": 2,
            "display_name": "TP-Link AX3000 Router",
            "subtitle": "Wi-Fi 6 | AX3000 | Gigabit",
        },
    },
    {
        "sku": "NET-0005",
        "name": "ASUS RT-AX54HP V2 AX1800 Wi-Fi 6 Router",
        "price_cents": 17900,
        "specs": {
            "wifi_standard": "Wi-Fi 6 (802.11ax)", "speed_mbps": 1800,
            "use_case": "networking", "rating": 4.3, "shipping_days": 2,
            "display_name": "ASUS RT-AX54HP AX1800",
            "subtitle": "Wi-Fi 6 | AX1800 | ASUS",
        },
    },
    {
        "sku": "NET-0006",
        "name": "ASUS DSL-AX82U AX5400 Wi-Fi 6 Modem Router",
        "price_cents": 44900,
        "specs": {
            "wifi_standard": "Wi-Fi 6 (802.11ax)", "speed_mbps": 5400,
            "use_case": "networking", "rating": 4.5, "shipping_days": 3,
            "display_name": "ASUS DSL-AX82U AX5400",
            "subtitle": "Wi-Fi 6 | AX5400 | Modem+Router",
        },
    },
    {
        "sku": "NET-0007",
        "name": "Starlink Standard Kit (Latest Generation)",
        "price_cents": 54900,
        "specs": {
            "wifi_standard": "Satellite Internet",
            "use_case": "networking", "rating": 4.4, "shipping_days": 7,
            "display_name": "Starlink Standard Kit",
            "subtitle": "Satellite Internet | 25-220 Mbps",
        },
    },
]

# ---------------------------------------------------------------------------
# GAMING HEADSETS
# ---------------------------------------------------------------------------
HEADSETS = [
    {
        "sku": "HDS-0001",
        "name": "RIG R5 SPEAR PRO HS Gaming Headset (Black)",
        "price_cents": 17900,
        "specs": {
            "wireless": False, "colour": "Black",
            "use_case": "gaming_headset", "rating": 4.1, "shipping_days": 3,
            "display_name": "RIG R5 SPEAR PRO HS",
            "subtitle": "Wired Gaming Headset",
        },
    },
    {
        "sku": "HDS-0002",
        "name": "Corsair VOID Wireless V2 Gaming Headset (Pink)",
        "price_cents": 19900,
        "specs": {
            "wireless": True, "colour": "Pink",
            "use_case": "gaming_headset", "rating": 4.3, "shipping_days": 2,
            "display_name": "Corsair VOID Wireless V2",
            "subtitle": "Wireless Gaming Headset | Pink",
        },
    },
    {
        "sku": "HDS-0003",
        "name": "Logitech G325 LIGHTSPEED Wireless Gaming Headset (White)",
        "price_cents": 19900,
        "specs": {
            "wireless": True, "colour": "White", "lightspeed": True,
            "use_case": "gaming_headset", "rating": 4.4, "shipping_days": 2,
            "display_name": "Logitech G325 LIGHTSPEED",
            "subtitle": "Wireless Gaming Headset | LIGHTSPEED",
        },
    },
    {
        "sku": "HDS-0004",
        "name": "HyperX Cloud Flight 2 Wired Gaming Headset",
        "price_cents": 21900,
        "specs": {
            "wireless": False,
            "use_case": "gaming_headset", "rating": 4.4, "shipping_days": 2,
            "display_name": "HyperX Cloud Flight 2",
            "subtitle": "Wired Gaming Headset | HyperX",
        },
    },
    {
        "sku": "HDS-0005",
        "name": "Logitech G Astro A20X PLAYSYNC Wireless Headset (Black)",
        "price_cents": 34900,
        "specs": {
            "wireless": True, "colour": "Black",
            "use_case": "gaming_headset", "rating": 4.5, "shipping_days": 2,
            "display_name": "Logitech G Astro A20X",
            "subtitle": "Wireless Gaming Headset | PLAYSYNC",
        },
    },
    {
        "sku": "HDS-0006",
        "name": "AceZone A-Blaze Hybrid ANC Bluetooth Wireless PC Gaming Headset (Black)",
        "price_cents": 35615,
        "specs": {
            "wireless": True, "colour": "Black", "anc": True, "bluetooth": True,
            "use_case": "gaming_headset", "rating": 4.3, "shipping_days": 3,
            "display_name": "AceZone A-Blaze ANC",
            "subtitle": "Wireless ANC Gaming Headset | Bluetooth",
        },
    },
]

# ---------------------------------------------------------------------------
# STORAGE
# ---------------------------------------------------------------------------
STORAGE = [
    {
        "sku": "STO-0001",
        "name": "SanDisk E30 Portable SSD Drive (1TB)",
        "price_cents": 16900,
        "specs": {
            "storage_type": "portable_ssd", "storage_gb": 1024,
            "use_case": "storage", "rating": 4.3, "shipping_days": 2,
            "display_name": "SanDisk E30 Portable SSD 1TB",
            "subtitle": "1TB Portable SSD | USB",
        },
    },
    {
        "sku": "STO-0002",
        "name": "Epson WorkForce Pro WF-3825 Multifunction Printer",
        "price_cents": 16900,
        "specs": {
            "category": "printer", "ppm_black": 21, "ppm_colour": 11,
            "use_case": "printer", "rating": 4.2, "shipping_days": 3,
            "display_name": "Epson WorkForce Pro WF-3825",
            "subtitle": "Multifunction Printer | 21ppm",
        },
    },
    {
        "sku": "STO-0003",
        "name": "Canon TS7760 Pixma Home Printer",
        "price_cents": 13900,
        "specs": {
            "category": "printer", "ppm_black": 15, "ppm_colour": 10,
            "use_case": "printer", "rating": 4.3, "shipping_days": 2,
            "display_name": "Canon TS7760 Pixma",
            "subtitle": "Home Printer | Colour Photo",
        },
    },
    {
        "sku": "STO-0004",
        "name": "Seagate Expansion Desktop 16TB Hard Drive",
        "price_cents": 49900,
        "specs": {
            "storage_type": "external_hdd", "storage_gb": 16384,
            "use_case": "storage", "rating": 4.4, "shipping_days": 3,
            "display_name": "Seagate Expansion 16TB",
            "subtitle": "16TB External HDD | USB",
        },
    },
    {
        "sku": "STO-0005",
        "name": "Samsung T7 Portable SSD Drive 1TB (Titan Gray)",
        "price_cents": 32900,
        "specs": {
            "storage_type": "portable_ssd", "storage_gb": 1024,
            "use_case": "storage", "rating": 4.5, "shipping_days": 2,
            "display_name": "Samsung T7 SSD 1TB (Titan Gray)",
            "subtitle": "1TB Portable SSD | Samsung T7",
        },
    },
    {
        "sku": "STO-0006",
        "name": "Samsung Portable SSD T7 Shield 1TB (Black)",
        "price_cents": 36900,
        "specs": {
            "storage_type": "portable_ssd", "storage_gb": 1024,
            "use_case": "storage", "rating": 4.6, "shipping_days": 2,
            "display_name": "Samsung T7 Shield 1TB (Black)",
            "subtitle": "1TB Rugged Portable SSD | IP65",
        },
    },
    {
        "sku": "STO-0007",
        "name": "SanDisk Creator Phone SSD with Magsafe 2TB",
        "price_cents": 39900,
        "specs": {
            "storage_type": "portable_ssd", "storage_gb": 2048,
            "magsafe": True,
            "use_case": "storage", "rating": 4.4, "shipping_days": 2,
            "display_name": "SanDisk Creator SSD 2TB MagSafe",
            "subtitle": "2TB MagSafe Portable SSD",
        },
    },
    {
        "sku": "STO-0008",
        "name": "WD My Book 16TB External Hard Drive",
        "price_cents": 67900,
        "specs": {
            "storage_type": "external_hdd", "storage_gb": 16384,
            "use_case": "storage", "rating": 4.4, "shipping_days": 3,
            "display_name": "WD My Book 16TB",
            "subtitle": "16TB External HDD | USB 3.0",
        },
    },
    {
        "sku": "STO-0009",
        "name": "Seagate Expansion Desktop 26TB Hard Drive",
        "price_cents": 74900,
        "specs": {
            "storage_type": "external_hdd", "storage_gb": 26624,
            "use_case": "storage", "rating": 4.4, "shipping_days": 4,
            "display_name": "Seagate Expansion 26TB",
            "subtitle": "26TB External HDD | USB",
        },
    },
    {
        "sku": "STO-0010",
        "name": "Samsung Portable T7 Shield SSD 4TB (Black)",
        "price_cents": 99900,
        "specs": {
            "storage_type": "portable_ssd", "storage_gb": 4096,
            "use_case": "storage", "rating": 4.7, "shipping_days": 2,
            "display_name": "Samsung T7 Shield 4TB (Black)",
            "subtitle": "4TB Rugged Portable SSD | IP65",
        },
    },
]


def seed_group(cur, conn, products: list[dict], group_name: str) -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    inserted = skipped = 0
    for p in products:
        cur.execute("SELECT sku FROM products WHERE sku = ?", (p["sku"],))
        if cur.fetchone():
            skipped += 1
            continue
        cur.execute(
            """INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at, image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                p["sku"],
                p["name"],
                p["price_cents"],
                CATALOG_CURRENCY,
                json.dumps(p["specs"]),
                1,
                now,
                f"/static/images/{p['sku']}.svg",
            ),
        )
        inserted += 1
    conn.commit()
    print(f"  {group_name}: inserted={inserted} skipped={skipped}")
    return inserted, skipped


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    total_before = cur.fetchone()[0]
    print(f"Products before seeding: {total_before}")
    print()

    groups = [
        (LAPTOPS, "Windows Laptops"),
        (GAMING_LAPTOPS_REAL, "Real Gaming Laptops"),
        (APPLE_PRODUCTS, "Apple Products"),
        (MONITORS, "Monitors"),
        (BAGS, "Bags/Cases"),
        (TABLETS, "Tablets"),
        (NETWORKING, "Networking/Routers"),
        (HEADSETS, "Gaming Headsets"),
        (STORAGE, "Storage/Printers"),
    ]

    total_ins = total_skip = 0
    for products, name in groups:
        ins, skip = seed_group(cur, conn, products, name)
        total_ins += ins
        total_skip += skip

    conn.close()

    conn2 = sqlite3.connect(DB_PATH)
    cur2 = conn2.cursor()
    cur2.execute("SELECT COUNT(*) FROM products")
    total_after = cur2.fetchone()[0]
    conn2.close()

    print()
    print(f"Done. Total inserted={total_ins} skipped={total_skip}")
    print(f"Products after seeding: {total_after}")
    print()
    print("Gaming laptops in catalog:")
    conn3 = sqlite3.connect(DB_PATH)
    cur3 = conn3.cursor()
    cur3.execute(
        "SELECT sku, name, price_cents FROM products "
        "WHERE (sku LIKE 'GAM-%' OR sku LIKE 'RGAM-%') ORDER BY price_cents"
    )
    for row in cur3.fetchall():
        print(f"  {row[0]}  ${row[2]//100:,}  {row[1][:65]}")
    conn3.close()


if __name__ == "__main__":
    main()
