"""Shared recommend leaf utilities — the foundation for the core/adapter stage split.

ARCHITECTURE NOTE — Core vs Adapter demarcation:
─────────────────────────────────────────────────
CORE (vertical-agnostic):
  • _brand_alias_map() / _manufacturer_specs() — reads from StoreProfile, already generic.
  • _brand_display_name() — normalized display name lookup via profile.
  • _candidate_matches_brand() — token-matching algorithm, works with any brand set.
  • _result_price_dollars() — extracts numeric price from candidate dict.

ADAPTER (product-type-specific, currently hardcoded electronics):
  • _extract_candidate_numeric_specs() — parses laptop-specific spec fields:
    ram_gb, storage_gb, display_inches, refresh_hz, gpu_vram_gb, has_dedicated_gpu,
    gaming_style, portable, nvidia, creator_hint, workstation_hint.
    A pharmacy vertical would parse: dosage_mg, interaction_count, schedule_class.
    A fashion vertical would parse: fabric_gsm, size_range, season.
  • The regex patterns inside _extract_candidate_numeric_specs that look for
    "rtx", "gtx", "geforce", "rog", "tuf", "legion", "alienware", etc.

MIGRATION PATH (Phase 2):
  Add `spec_extraction_rules` slot to StoreProfile — defines which fields to
  extract and how to regex-parse them from product text. The function becomes
  a generic rule executor rather than hardcoded electronics parser.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List


def _manufacturer_specs() -> Dict[str, Dict[str, Any]]:
    from src.app.platform.store_profile import profile_slot

    raw = profile_slot("manufacturers", default={}) or {}
    return {
        str(k).strip().lower(): (v if isinstance(v, dict) else {})
        for k, v in raw.items()
        if str(k).strip()
    } if isinstance(raw, dict) else {}


def _brand_alias_map() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for manufacturer, spec in _manufacturer_specs().items():
        tokens = [manufacturer]
        tokens.extend(str(x).strip().lower() for x in (spec.get("aliases") or []) if str(x).strip())
        tokens.extend(str(x).strip().lower() for x in (spec.get("lines") or []) if str(x).strip())
        out[manufacturer] = list(dict.fromkeys(tokens))
    return out


def _candidate_matches_brand(candidate: Dict[str, Any] | None, brands: List[str] | None) -> bool:
    c = candidate or {}
    req = [str(b or "").strip().lower() for b in (brands or []) if str(b or "").strip()]
    if not req:
        return False
    name = str(c.get("name") or "").lower()
    sku = str(c.get("sku") or "").lower()
    text_blob = f"{name} {sku}"
    alias = _brand_alias_map()
    for b in req:
        probes = alias.get(b, [b])
        if any(p in text_blob for p in probes):
            return True
    return False


def _brand_display_name(brand: str | None) -> str:
    key = str(brand or "").strip().lower()
    if not key:
        return ""
    spec = _manufacturer_specs().get(key) or {}
    display = str(spec.get("display") or "").strip()
    return display or key.title()


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


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER — Electronics-specific spec extraction.
# Parses laptop/electronics product fields. The regex patterns, field names,
# and token lists ("rtx", "rog", "tuf", "legion") are all electronics-specific.
# Phase 2: replace with StoreProfile["spec_extraction_rules"].
# ═══════════════════════════════════════════════════════════════════════════════

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
