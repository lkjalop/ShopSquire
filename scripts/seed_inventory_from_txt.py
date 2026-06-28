"""Seed the catalog from a free-form inventory .txt (the merchant's product dump).

The .txt has products separated by lines of colons (``::::``); each block is a name (1-2 lines),
a ``Price: $N`` line, and free-text spec lines. This parses every block, extracts structured specs,
classifies category + use_case (so the recommendation choice-lanes + ranking fire), and upserts into
``products`` + ``inventory`` (idempotent per-SKU; AUD prices). Run with ``--dry-run`` to print the parse
without touching the DB.

Usage:
  python scripts/seed_inventory_from_txt.py [path.txt] [--dry-run]
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

_DEFAULT_TXT = "docs/2026-06-28 laptop-products-new.txt"
_SEP = re.compile(r"^:{6,}\s*$")
# section headers that appear alone on a block line and switch the current category
_SECTION = {
    "bags": "bag", "monitors": "monitor", "wi-fi routers": "router", "wifi routers": "router",
    "gaming headsets": "headset", "hard drive": "hard_drive", "hard drives": "hard_drive",
}


def _price_cents(block: str) -> Optional[int]:
    m = re.search(r"price[:\s]*\$?\s*([\d,]+(?:\.\d{1,2})?)", block, re.IGNORECASE)
    if not m:
        return None
    try:
        return int(round(float(m.group(1).replace(",", "")) * 100))
    except ValueError:
        return None


def _first_int(rx: str, text: str) -> Optional[int]:
    m = re.search(rx, text, re.IGNORECASE)
    if not m:
        return None
    g = next((x for x in m.groups() if x), None)  # first non-None group (handles alternation)
    return int(g) if g else None


def _storage_gb(text: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*(TB|GB)\s*(?:M\.2\s*)?(?:PCIe\s*)?(?:NVMe\s*)?SSD|(\d+)\s*(TB|GB)\s+(?:SSD\s+)?storage|\[(\d+)(TB|GB)", text, re.IGNORECASE)
    if not m:
        m2 = re.search(r"Total Storage\s*(\d+)\s*(TB|GB)", text, re.IGNORECASE)
        if not m2:
            return None
        val, unit = int(m2.group(1)), m2.group(2)
        return val * 1024 if unit.upper() == "TB" else val
    val = next((g for g in (m.group(1), m.group(3), m.group(5)) if g), None)
    unit = next((g for g in (m.group(2), m.group(4), m.group(6)) if g), "GB")
    if val is None:
        return None
    return int(val) * 1024 if unit.upper() == "TB" else int(val)


def _gpu(text: str) -> tuple[Optional[str], bool]:
    m = re.search(r"(GeForce RTX\s*\d{3,4}|RTX\s*\d{3,4})", text, re.IGNORECASE)
    if m:
        return m.group(1).upper().replace("GEFORCE ", "GeForce "), True
    for integ in ("Radeon Graphics", "Radeon graphics", "Intel Arc Graphics", "Arc Graphics",
                  "Iris Xe", "UHD Graphics", "Adreno", "Apple", "Mali", "Intel Graphics"):
        if integ.lower() in text.lower():
            return integ, False
    return None, False


def _use_case(name: str, specs: Dict[str, Any], price_cents: Optional[int]) -> str:
    n = name.lower()
    if specs.get("gaming_style"):
        return "gaming"
    # discrete GPU on a non-gaming-branded premium machine → creative/content
    if specs.get("gpu_discrete"):
        return "content_creation"
    if any(b in n for b in ("legion", "rog ", "omen", "predator", "nitro", "tuf", "alienware", "katana", "victus")):
        return "gaming"
    if price_cents is not None and price_cents <= 80000:
        return "value"
    if any(b in n for b in ("oled", "prestige", "creator", "ryzen 9", "ultra 9")):
        return "content_creation"
    return "business"


def _category(name: str, block: str, section: str) -> str:
    # NAME-based detection wins over the section hint (the .txt order means a laptop can follow the
    # "Hard drive" header, and a tablet can follow "Monitors" — so a stale section must never override
    # an unambiguous name).
    n, b = name.lower(), block.lower()
    if any(k in n for k in ("backpack", "brief", "folio", "attache", "rucksack", "sleeve")):
        return "bag"
    if "monitor" in n:
        return "monitor"
    if any(k in n for k in ("router", "range extender", "starlink", "modem")):
        return "router"
    if "headset" in n:
        return "headset"
    if "printer" in n:
        return "printer"
    if any(k in n for k in ("hard drive", "portable ssd", "ssd drive", "my book", "expansion desktop")):
        return "hard_drive"
    if ("ipad" in n or "galaxy tab" in n or re.search(r"\btab\b", n) or "tablet type" in b) and "macbook" not in n:
        return "tablet"
    # a clear laptop/notebook signal (processor/chip + RAM/GB + a screen size) beats any section hint
    if (re.search(r"processor|chip|snapdragon|core ultra|ryzen|core i\d", b) and re.search(r"\bGB\b|\bRAM\b", b)) \
            or any(k in n for k in ("macbook", "laptop", "notebook")):
        return "laptop"
    return section or "laptop"


def _laptop_specs(name: str, block: str, price_cents: Optional[int]) -> Dict[str, Any]:
    specs: Dict[str, Any] = {}
    # MacBook/minimal blocks carry specs in the NAME as "1TB/24GB" or "256GB/8GB"
    nm_sd = re.search(r"(\d+)\s*(TB|GB)\s*/\s*(\d+)\s*GB", name, re.IGNORECASE)
    ram = _first_int(r"(\d+)\s*GB\s*RAM", block) or _first_int(r"RAM\s*\(GB\)\s*(\d+)", block) or _first_int(r"with\s+(\d+)\s*GB\s*RAM", block)
    if not ram and nm_sd:
        ram = int(nm_sd.group(3))
    if ram:
        specs["ram_gb"] = ram
    sg = _storage_gb(block)
    if not sg and nm_sd:
        sg = int(nm_sd.group(1)) * (1024 if nm_sd.group(2).upper() == "TB" else 1)
    if sg:
        specs["storage_gb"] = sg
    hz = _first_int(r"(\d+)\s*Hz", block)
    if hz:
        specs["refresh_hz"] = hz
    di = re.search(r"(\d{1,2}(?:\.\d)?)[\"”]", block)
    if di:
        specs["display_inches"] = float(di.group(1))
    gpu, discrete = _gpu(block)
    if gpu:
        specs["gpu"] = gpu
    specs["gpu_discrete"] = discrete
    if discrete:
        specs["gaming_style"] = bool(re.search(r"gaming", block, re.IGNORECASE) or re.search(r"legion|rog |omen|predator|nitro|tuf|alienware|katana|victus", name, re.IGNORECASE))
        v = re.search(r"RTX\s*\d{3,4}\s*(?:graphics\s*)?(\d+)\s*GB", block, re.IGNORECASE)
        if v:
            specs["gpu_vram_gb"] = int(v.group(1))
    for os_name, key in (("windows 11", "Windows 11"), ("macos", "macOS"), ("chrome os", "ChromeOS"),
                         ("android", "Android"), ("ipados", "iPadOS")):
        if os_name in block.lower():
            specs["os"] = key
            break
    wm = re.search(r"Wi-?Fi\s*(7|6E|6|5)", block, re.IGNORECASE)
    if wm:
        specs["wifi"] = f"Wi-Fi {wm.group(1).upper()}"
    if re.search(r"FHD webcam|1080p", block, re.IGNORECASE):
        specs["webcam"] = "1080p webcam"
    elif re.search(r"webcam", block, re.IGNORECASE):
        specs["webcam"] = "HD webcam"
    if re.search(r"thunderbolt", block, re.IGNORECASE):
        specs["docking"] = "Thunderbolt 4"
    bl = re.search(r"Battery life\s*(?:Up to\s*)?(\d+)\s*Hours", block, re.IGNORECASE)
    if bl:
        specs["battery_hours"] = int(bl.group(1))
    specs["use_case"] = _use_case(name, specs, price_cents)
    return specs


def parse_inventory(text: str) -> List[Dict[str, Any]]:
    blocks, cur, section = [], [], ""
    for line in text.splitlines():
        if _SEP.match(line):
            if cur:
                blocks.append("\n".join(cur).strip())
            cur = []
            continue
        cur.append(line)
    if cur:
        blocks.append("\n".join(cur).strip())

    products: List[Dict[str, Any]] = []
    for block in blocks:
        b = block.strip()
        if not b:
            continue
        low = b.lower().strip()
        if low in _SECTION:  # a lone section header → switch context, no product
            section = _SECTION[low]
            continue
        lines = [ln.strip() for ln in b.splitlines() if ln.strip()]
        if not lines:
            continue
        # name = lines until the Price line (or first 2 lines)
        name_lines = []
        for ln in lines:
            if re.match(r"price", ln, re.IGNORECASE):
                break
            name_lines.append(ln)
            if len(name_lines) >= 3:
                break
        name = re.sub(r"\s+", " ", " ".join(name_lines)).strip(" -[")
        if not name or len(name) < 4:
            continue
        price = _price_cents(b)
        category = _category(name, b, section)
        specs: Dict[str, Any] = {"category": category}
        if category == "laptop":
            specs.update(_laptop_specs(name, b, price))
        elif category == "tablet":
            specs["use_case"] = "tablet"
            r = _first_int(r"RAM\s*\(GB\)\s*(\d+)|(\d+)\s*GB\s*RAM", b)
            if r:
                specs["ram_gb"] = r
        sku_prefix = {"laptop": "LAP", "tablet": "TAB", "monitor": "MON", "bag": "BAG",
                      "router": "NET", "headset": "AUD", "printer": "PRN", "hard_drive": "HDD"}.get(category, "ACC")
        sku = f"{sku_prefix}-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:8].upper()}"
        products.append({"sku": sku, "name": name, "price_cents": price, "category": category, "specs": specs})
    return products


def seed(db, products: List[Dict[str, Any]]) -> Dict[str, int]:
    from sqlalchemy import text as _t
    inserted = 0
    for i, p in enumerate(products):
        if p["price_cents"] is None:
            continue
        sku = p["sku"]
        row = db.execute(_t("SELECT id FROM products WHERE sku = :s"), {"s": sku}).fetchone()
        if row:
            pid = row[0]
        else:
            pid = str(uuid.uuid4())
            db.execute(_t(
                "INSERT INTO products (id, sku, name, price_cents, currency, specs, active, updated_at, image_url) "
                "VALUES (:id, :sku, :name, :pc, 'AUD', :specs, 1, :ua, :img)"),
                {"id": pid, "sku": sku, "name": p["name"], "pc": p["price_cents"],
                 "specs": json.dumps(p["specs"]), "ua": datetime.utcnow(), "img": f"/static/images/{sku}.svg"})
            inserted += 1
        has_inv = db.execute(_t("SELECT 1 FROM inventory WHERE product_id = :pid LIMIT 1"), {"pid": pid}).fetchone()
        if not has_inv:
            db.execute(_t("INSERT INTO inventory (id, product_id, stock, warehouse, updated_at) "
                          "VALUES (:id, :pid, :st, 'default', :ua)"),
                       {"id": str(uuid.uuid4()), "pid": pid, "st": 8 + (i % 15), "ua": datetime.utcnow()})
    db.commit()
    return {"inserted": inserted, "total_parsed": len(products)}


def main() -> None:
    args = [a for a in sys.argv[1:]]
    dry = "--dry-run" in args
    paths = [a for a in args if not a.startswith("--")]
    txt_path = Path(paths[0]) if paths else Path(_DEFAULT_TXT)
    products = parse_inventory(txt_path.read_text(encoding="utf-8", errors="replace"))
    by_cat: Dict[str, int] = {}
    for p in products:
        by_cat[p["category"]] = by_cat.get(p["category"], 0) + 1
    print(f"Parsed {len(products)} products from {txt_path}: {by_cat}")
    laptops = [p for p in products if p["category"] == "laptop"]
    print("\n-- laptop sample (sku | $price | use_case | gpu | ram/stor | name) --")
    for p in laptops:
        s = p["specs"]
        pr = f"${p['price_cents']//100}" if p["price_cents"] else "(no price)"
        print(f"  {p['sku']} | {pr:>7} | {s.get('use_case','?'):14} | {str(s.get('gpu','-'))[:18]:18} | "
              f"{s.get('ram_gb','?')}GB/{s.get('storage_gb','?')} | {p['name'][:52]}")
    if dry:
        print("\n(dry-run — no DB writes)")
        return
    from src.app.models.db import db_session
    with db_session() as db:
        print("\n", seed(db, products))


if __name__ == "__main__":
    main()
