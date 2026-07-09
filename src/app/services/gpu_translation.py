"""Desktop→laptop GPU translation (Phase W5, agnostic mechanism over config data).

Game/system requirements name DESKTOP GPUs (see steam_requirements connector docstring);
the laptop part with the same number is roughly one class slower. This module loads the
curated equivalence table ``config/knowledge_pool/gpu_translation.json`` (override with
``GPU_TRANSLATION_PATH``) and answers two questions for the fit layer:

  - ``desktop_req_to_laptop_tier("GTX 1060 6GB")`` → what LAPTOP tier / VRAM a catalog
    machine needs to satisfy a requirement that names that desktop part;
  - ``laptop_gpu_tier("RTX 4060 Laptop GPU")`` → the tier of a catalog laptop's GPU.

Fit rule: laptop_tier >= required tier ⇒ the laptop meets the requirement. Matching is
case-insensitive substring on known names, longest name wins ("RTX 3050 Ti" beats
"RTX 3050"). WHICH GPUs exist and their tiers is config flavour; this module is only the
lookup mechanism. Cache reloads on file mtime drift (same pattern as knowledge_pool.py)
and force-reloads under PYTEST_CURRENT_TEST. Fail-safe contract: never raises — missing/
malformed table or unknown GPU string → None.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Tuple

_TABLE_ENV = "GPU_TRANSLATION_PATH"
_DEFAULT_TABLE_PATH = os.path.join("config", "knowledge_pool", "gpu_translation.json")

# Single-table cache with mtime-drift invalidation (pattern: knowledge_pool.py).
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_META: Dict[str, Tuple[str, Optional[int], Optional[int]]] = {}


def load_table(force_reload: bool = False) -> Optional[Dict[str, Any]]:
    """The translation table dict, cached until the file's mtime/size drifts. None if absent."""
    try:
        path = os.getenv(_TABLE_ENV) or _DEFAULT_TABLE_PATH
        if os.getenv("PYTEST_CURRENT_TEST"):  # tests may repoint the file; avoid order flakes
            force_reload = True
        mtime_ns: Optional[int] = None
        size: Optional[int] = None
        try:
            if os.path.exists(path):
                st = os.stat(path)
                mtime_ns = getattr(st, "st_mtime_ns", None) or int(st.st_mtime * 1_000_000_000)
                size = st.st_size
        except Exception:
            pass
        if mtime_ns is None:
            _CACHE.pop("table", None)
            _CACHE_META.pop("table", None)
            return None
        meta = _CACHE_META.get("table")
        if not force_reload and "table" in _CACHE and meta == (path, mtime_ns, size):
            return _CACHE["table"]
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return None
        _CACHE["table"] = data
        _CACHE_META["table"] = (path, mtime_ns, size)
        return data
    except Exception:
        return None


def desktop_req_to_laptop_tier(gpu_string: str) -> Optional[Dict[str, Any]]:
    """Translate a DESKTOP GPU requirement string into the minimum laptop bar.

    Case-insensitive substring match against known desktop names; the longest matching
    name wins (so "GTX 1650 Ti" is not read as "GTX 1650"). Returns
    ``{"tier": int, "vram_gb_min": int, "desktop": str, "laptop_equiv_min": [...]}``
    or None when no known desktop part appears in the string.
    """
    try:
        table = load_table()
        if not table:
            return None
        needle = str(gpu_string or "").lower()
        if not needle.strip():
            return None
        best: Optional[Dict[str, Any]] = None
        best_len = 0
        for entry in table.get("desktop_to_laptop") or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("desktop") or "").lower()
            if name and name in needle and len(name) > best_len:
                best, best_len = entry, len(name)
        if best is None:
            return None
        return {
            "tier": int(best.get("tier") or 0),
            "vram_gb_min": int(best.get("laptop_vram_gb_min") or 0),
            "desktop": best.get("desktop"),
            "laptop_equiv_min": list(best.get("laptop_equiv_min") or []),
        }
    except Exception:
        return None


def laptop_gpu_tier(gpu_string: str) -> Optional[int]:
    """Tier of a LAPTOP GPU string (case-insensitive substring, longest name wins).
    None when the GPU is not in the table — the caller must treat unknown as unknown,
    never as tier 0."""
    try:
        table = load_table()
        if not table:
            return None
        needle = str(gpu_string or "").lower()
        if not needle.strip():
            return None
        best_tier: Optional[int] = None
        best_len = 0
        for name, tier in (table.get("laptop_gpu_tiers") or {}).items():
            n = str(name or "").lower()
            if n and n in needle and len(n) > best_len:
                try:
                    best_tier, best_len = int(tier), len(n)
                except (TypeError, ValueError):
                    continue
        return best_tier
    except Exception:
        return None
