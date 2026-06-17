"""StoreProfile loader — the enforceable core/adapter boundary (R1).

The agnostic core owns MECHANISMS; a StoreProfile owns FLAVOUR (brands, price floors,
product-type rules, use-case→spec mappings, NQE question sets, spec-extraction patterns).
This module is the canonical, validated, cached loader. Wiring a piece of recommend.py /
query_decomposer / nqe to read from here (instead of an inline literal) is how flavour
is excised one slot at a time — each behind a characterization test.

Profiles live in config/store_profiles/<id>.json. Adding pharmacy.json with the same
shape is the agnostic proof. Pure + cached; never raises on read (returns {} / default).
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)

_PROFILES_DIR_ENV = "STORE_PROFILES_DIR"
_DEFAULT_DIR = os.path.join("config", "store_profiles")
_DEFAULT_PROFILE_ID = "electronics"

# Slots a profile is expected to carry. Missing slots are tolerated at read time
# (callers default), but in strict mode (CI/test) a malformed profile fails closed.
_KNOWN_SLOTS = frozenset({
    "id", "version", "known_brands", "brand_label_patterns", "brand_price_floors_usd",
    "primary_types", "price_bands_usd", "use_cases", "spec_constraints",
    "upsell_companions", "cv_returns_pack",
})


def _profiles_dir() -> Path:
    return Path(os.getenv(_PROFILES_DIR_ENV, _DEFAULT_DIR))


@lru_cache(maxsize=16)
def get_store_profile(profile_id: str = _DEFAULT_PROFILE_ID) -> Dict[str, Any]:
    """Load + validate a store profile by id. Cached. Falls back to the electronics
    profile if the requested id is missing. Returns {} only if nothing loads.

    Strict mode (STORE_PROFILE_STRICT=1, set in CI/test) raises on malformed JSON so a
    broken profile fails the build rather than silently degrading recommendations."""
    strict = str(os.getenv("STORE_PROFILE_STRICT", "0")).strip().lower() in ("1", "true", "yes")
    pid = (profile_id or _DEFAULT_PROFILE_ID).strip() or _DEFAULT_PROFILE_ID
    path = _profiles_dir() / f"{pid}.json"
    if not path.exists():
        # Fail-closed: in strict mode (prod/CI) a missing requested profile MUST NOT silently
        # become electronics — a tenant/profile typo routing pharmacy through laptop rules is a
        # correctness + compliance hazard. Only dev/test (non-strict) falls back for convenience.
        if strict and pid != _DEFAULT_PROFILE_ID:
            _log.error("store profile %r not found at %s and STORE_PROFILE_STRICT=1 — failing closed", pid, path)
            raise FileNotFoundError(f"store profile {pid!r} not found (strict mode forbids electronics fallback)")
        path = _profiles_dir() / f"{_DEFAULT_PROFILE_ID}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not data.get("id"):
            raise ValueError(f"store profile {pid} missing required 'id'")
        return data
    except Exception as exc:
        _log.warning("store profile load failed for %s: %s", pid, exc)
        if strict:
            raise
        return {}


def profile_slot(slot: str, *, profile_id: str = _DEFAULT_PROFILE_ID, default: Any = None) -> Any:
    """Read one slot from a profile with a default. The canonical accessor for excised
    flavour (e.g. brand_price_floors_usd) so call-sites never inline literals."""
    try:
        val = get_store_profile(profile_id).get(slot)
        return val if val is not None else default
    except Exception:
        return default


def brand_price_floors(profile_id: str = _DEFAULT_PROFILE_ID) -> Dict[str, int]:
    """Per-brand realistic price floor (USD) — excised from recommend.py
    _BRAND_PRICE_FLOORS. Used to surface a budget-mismatch clarifying question."""
    raw = profile_slot("brand_price_floors_usd", profile_id=profile_id, default={}) or {}
    out: Dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[str(k).lower()] = int(v)
        except Exception:
            continue
    return out


def reset_cache() -> None:
    """Clear the profile cache — MUST be called by the test isolation fixture so a
    profile loaded under one tenant/vertical can't leak into the next test."""
    try:
        get_store_profile.cache_clear()
    except Exception:
        pass
