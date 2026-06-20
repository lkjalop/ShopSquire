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
from functools import lru_cache
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
# CORE — Generic spec extraction driven by StoreProfile["spec_extraction_rules"].
# A vertical defines numeric fields (spec_key + ordered regex patterns) and boolean
# flags (token presence). Verticals WITHOUT the slot fall back to the electronics
# inline parser below (byte-identical, zero risk) — that inline parser is the
# electronics ADAPTER until/unless it too migrates to rules behind the parity grid.
# ═══════════════════════════════════════════════════════════════════════════════

@lru_cache(maxsize=8)
def _spec_extraction_rules_for(pid: str):
    from src.app.platform.store_profile import profile_slot
    raw = profile_slot("spec_extraction_rules", profile_id=pid, default=None)
    if not isinstance(raw, dict):
        return None
    numeric = []
    for r in raw.get("numeric") or []:
        out = r.get("out")
        if not out:
            continue
        pats = [
            (re.compile(p["regex"], re.IGNORECASE), int(p.get("group", 1)), float(p.get("scale", 1.0)))
            for p in (r.get("patterns") or [])
            if isinstance(p, dict) and p.get("regex")
        ]
        numeric.append((out, r.get("spec_key"), pats))
    flags = [
        (f.get("out"), tuple(str(t).lower() for t in (f.get("any") or [])))
        for f in (raw.get("flags") or [])
        if isinstance(f, dict) and f.get("out")
    ]
    return {"numeric": numeric, "flags": flags}


def reset_cache() -> None:
    """Clear the per-profile spec-extraction-rules cache (test isolation / reload)."""
    _spec_extraction_rules_for.cache_clear()


def _candidate_text_blob(candidate: Dict[str, Any], specs: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(candidate.get("name") or ""),
            " ".join(str(x) for x in (candidate.get("features") or []) if x is not None),
            json.dumps(specs, ensure_ascii=False, default=str),
        ]
    ).lower()


def _specs_from_rules(candidate: Dict[str, Any], rules: dict) -> Dict[str, Any]:
    specs = candidate.get("specs") if isinstance(candidate.get("specs"), dict) else {}
    text = _candidate_text_blob(candidate, specs)

    def _as_float(value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except Exception:
            return None

    out: Dict[str, Any] = {}
    for out_key, spec_key, pats in rules["numeric"]:
        val = _as_float(specs.get(spec_key)) if spec_key else None
        if val is None:
            for rx, grp, scale in pats:
                m = rx.search(text)
                if m:
                    try:
                        val = float(m.group(grp)) * scale
                    except Exception:
                        val = None
                    break
        out[out_key] = val
    for out_key, toks in rules["flags"]:
        out[out_key] = any(t in text for t in toks)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# ADAPTER — Electronics-specific spec extraction (inline fallback).
# Used only when the active profile defines no spec_extraction_rules. Parses
# laptop/electronics fields; the regexes/token lists are electronics flavour.
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_candidate_numeric_specs(candidate: Dict[str, Any]) -> Dict[str, Any]:
    from src.app.platform.store_profile import active_profile_id
    _rules = _spec_extraction_rules_for(active_profile_id())
    if _rules is not None:
        return _specs_from_rules(candidate, _rules)

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
