"""Profile-driven product spec summary for narration (agnostic core).

The per-product spec line shown to the LLM (and usable for tradeoff narration) is built from the
ACTIVE StoreProfile's ``narration_spec_dimensions`` slot — NOT hardcoded electronics specs. Each
dimension is ``{"label": str, "variants": [{"key": str, "unit": str?}]}``; the first variant whose
key is present in the product's ``specs`` wins (so e.g. GPU model falls back to VRAM for electronics,
while pharmacy surfaces active ingredient / strength / form). This keeps the narration vocabulary
vertical-blind in core: a fashion or pharmacy vertical describes its OWN tradeoffs with zero code
change, and recommend.py stops hardcoding GPU/refresh/RAM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def spec_dimensions(profile_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The active vertical's narration spec dimensions (ordered). Empty list when the profile lacks
    the slot — the caller then renders 'specs unavailable' rather than inventing electronics fields.
    profile_slot is defensive (never raises), so no try/except (keeps off the silent-except ratchet)."""
    from src.app.platform.store_profile import profile_slot
    dims = profile_slot("narration_spec_dimensions", profile_id=profile_id, default=None)
    return [d for d in dims if isinstance(d, dict)] if isinstance(dims, list) else []


def _format_dimension(dim: Dict[str, Any], specs: Dict[str, Any]) -> Optional[str]:
    label = str(dim.get("label") or "").strip()
    for variant in (dim.get("variants") or []):
        if not isinstance(variant, dict):
            continue
        key = variant.get("key")
        val = specs.get(key) if key else None
        if val in (None, "", [], {}):
            continue
        unit = str(variant.get("unit") or "")
        return f"{label}: {val}{unit}" if label else f"{val}{unit}"
    return None


def spec_summary_line(result: Dict[str, Any], rank: int = 0, *, profile_id: Optional[str] = None) -> str:
    """`[N] Name ($price) — Label: val | Label: val` from the profile's narration dimensions.
    Vertical-blind: the labels/keys/units all come from the StoreProfile, never from this module."""
    specs = result.get("specs") if isinstance(result.get("specs"), dict) else {}
    parts: List[str] = []
    for dim in spec_dimensions(profile_id):
        line = _format_dimension(dim, specs)
        if line:
            parts.append(line)
    price_cents = result.get("price_cents") or 0
    try:
        price_str = f"${int(float(price_cents) / 100):,}" if float(price_cents) > 0 else ""
    except Exception:
        price_str = ""
    spec_str = " | ".join(parts) if parts else "specs unavailable"
    name = result.get("name") or "Unknown"
    return f"[{rank + 1}] {name} ({price_str}) — {spec_str}"
