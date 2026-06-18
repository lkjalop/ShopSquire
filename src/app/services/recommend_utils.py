"""Shared recommend leaf utilities — the foundation for the core/adapter stage split.

These are the small, PURE helpers (no DB, no request locals, no closures) that more than one
extracted stage needs. Pulling them here breaks the circular-import knot: a stage service
(budget advisor, narration, fast-path …) can import these without importing the router, and the
router re-exports them so its own call-sites stay unchanged.

CORE mechanism: brand-token matching, brand display, price normalisation.
ADAPTER (flavour): the brand alias / display maps below are still inline electronics flavour
(thinkpad/legion/alienware …). They are the Phase-2 profile-back target (a non-electronics
vertical supplies its own aliases via the StoreProfile `manufacturers` map) — which is why this
module is intentionally NOT yet on the no-flavour-in-core lint list, exactly like
recommend_image_hints.py. Tracked, not hidden.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def _candidate_matches_brand(candidate: Dict[str, Any] | None, brands: List[str] | None) -> bool:
    c = candidate or {}
    req = [str(b or "").strip().lower() for b in (brands or []) if str(b or "").strip()]
    if not req:
        return False
    name = str(c.get("name") or "").lower()
    sku = str(c.get("sku") or "").lower()
    text_blob = f"{name} {sku}"
    alias = {
        "apple": ["apple", "macbook", "imac"],
        "microsoft": ["microsoft", "surface"],
        "asus": ["asus", "vivobook", "zenbook", "rog", "tuf"],
        "lenovo": ["lenovo", "ideapad", "thinkpad", "yoga", "legion"],
        "hp": ["hp", "envy", "victus", "omen", "omnibook", "elitebook", "probook"],
        "dell": ["dell", "inspiron", "xps", "latitude", "vostro"],
        "msi": ["msi", "stealth", "raider", "titan"],
        "alienware": ["alienware"],
        "acer": ["acer", "swift", "aspire", "predator", "nitro"],
        "samsung": ["samsung", "galaxy book"],
        "razer": ["razer", "blade"],
        "gigabyte": ["gigabyte", "aorus"],
        "toshiba": ["toshiba", "dynabook"],
    }
    for b in req:
        probes = alias.get(b, [b])
        if any(p in text_blob for p in probes):
            return True
    return False


def _brand_display_name(brand: str | None) -> str:
    key = str(brand or "").strip().lower()
    return {
        "apple": "Apple",
        "asus": "ASUS",
        "lenovo": "Lenovo",
        "hp": "HP",
        "dell": "Dell",
        "msi": "MSI",
        "alienware": "Alienware",
        "microsoft": "Microsoft Surface",
        "acer": "Acer",
        "samsung": "Samsung",
        "razer": "Razer",
        "gigabyte": "Gigabyte",
        "toshiba": "Toshiba",
        "windows": "Windows",
    }.get(key, key.capitalize() if key else "")


def _result_price_dollars(row: Dict[str, Any] | None) -> float | None:
    r = row or {}
    try:
        if isinstance(r.get("price"), (int, float)):
            p = float(r.get("price"))
            if p > 0:
                return p
    except Exception:
        pass
    try:
        if isinstance(r.get("price_cents"), (int, float)):
            pc = float(r.get("price_cents"))
            if pc > 0:
                return round(pc / 100.0, 2)
    except Exception:
        pass
    return None


def _extract_candidate_numeric_specs(candidate: Dict[str, Any]) -> Dict[str, Any]:
    specs = candidate.get("specs") if isinstance(candidate.get("specs"), dict) else {}
    text = " ".join(
        [
            str(candidate.get("name") or ""),
            " ".join(str(x) for x in (candidate.get("features") or []) if x is not None),
            json.dumps(specs, ensure_ascii=False, default=str),
        ]
    ).lower()

    def _as_float(value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except Exception:
            return None

    ram = _as_float(specs.get("ram_gb"))
    storage = _as_float(specs.get("storage_gb"))
    display = _as_float(specs.get("display_inches"))
    refresh = _as_float(specs.get("refresh_hz"))
    gpu_vram = _as_float(specs.get("gpu_vram_gb"))
    if ram is None:
        m = re.search(r"\b(8|12|16|24|32|64)\s*gb\s*ram\b", text)
        ram = float(m.group(1)) if m else None
    if storage is None:
        m = re.search(r"\b(256|512|1024|2048)\s*gb\b", text)
        if m:
            storage = float(m.group(1))
        else:
            m_tb = re.search(r"\b([12])\s*tb\b", text)
            storage = float(m_tb.group(1)) * 1024.0 if m_tb else None
    if display is None:
        m = re.search(r"\b(13(?:\.\d)?|14(?:\.\d)?|15(?:\.\d)?|16(?:\.\d)?|17(?:\.\d)?)\s*(?:in|inch|\"|”)", text)
        display = float(m.group(1)) if m else None
    if refresh is None:
        m = re.search(r"\b(90|120|144|165|240)\s*hz\b", text)
        refresh = float(m.group(1)) if m else None
    if gpu_vram is None:
        m = re.search(r"\b(4|6|8|12|16)\s*gb\s*(?:vram|gpu)\b", text)
        gpu_vram = float(m.group(1)) if m else None

    gpu_text = str(specs.get("gpu") or "").lower()
    integrated_gpu = any(
        tok in f"{gpu_text} {text}"
        for tok in (
            "integrated",
            "intel uhd",
            "intel iris",
            "intel graphics",
            "radeon graphics",
            "amd radeon graphics",
            "qualcomm adreno",
            "adreno graphics",
        )
    )
    discrete_gpu = any(
        tok in f"{gpu_text} {text}"
        for tok in ("rtx", "gtx", "geforce", "rx 6", "rx 7", "rx 8", "arc a", "nvidia", "dedicated gpu")
    ) or (
        bool(gpu_text)
        and not integrated_gpu
        and any(tok in gpu_text for tok in ("radeon rx", "geforce", "rtx", "gtx", "arc a", "quadro"))
    )
    gaming_style = any(
        tok in text for tok in ("gaming", "rog", "tuf", "legion", "raider", "katana", "predator", "nitro", "alienware", "omen")
    )
    portable = bool(
        ("thin" in text or "light" in text or "ultrabook" in text or "air" in text)
        or (display is not None and display <= 14.5)
    )
    workstation_hint = any(tok in text for tok in ("workstation", "quadro", "rtx a", "studio"))
    nvidia = any(tok in text for tok in ("rtx", "gtx", "geforce", "nvidia"))
    creator_hint = any(tok in text for tok in ("creator", "studio", "oled", "premiere", "davinci"))
    return {
        "ram_gb": ram,
        "storage_gb": storage,
        "display_inches": display,
        "refresh_hz": refresh,
        "gpu_vram_gb": gpu_vram,
        "has_dedicated_gpu": discrete_gpu,
        "gaming_style": gaming_style,
        "portable": portable,
        "workstation_hint": workstation_hint,
        "nvidia": nvidia,
        "creator_hint": creator_hint,
    }
