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
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

_log = logging.getLogger(__name__)

_PROFILES_DIR_ENV = "STORE_PROFILES_DIR"
_DEFAULT_DIR = os.path.join("config", "store_profiles")
_DEFAULT_PROFILE_ID = "electronics"

# ── Active-vertical selector ─────────────────────────────────────────────────────────────────
# Which StoreProfile is active for THIS request/tenant. Resolution order:
#   explicit profile_id arg  →  per-request ContextVar  →  STORE_PROFILE_ID env  →  electronics.
# The ContextVar makes the core tenant-aware WITHOUT threading profile_id through every consumer:
# a request handler sets it once, every no-arg get_store_profile() reads the active vertical.
_ACTIVE_PROFILE_ID: "ContextVar[Optional[str]]" = ContextVar("active_store_profile_id", default=None)


def active_profile_id() -> str:
    """Resolve the active vertical id (never empty): ContextVar → STORE_PROFILE_ID env → default."""
    cv = _ACTIVE_PROFILE_ID.get()
    if cv and str(cv).strip():
        return str(cv).strip()
    env = os.getenv("STORE_PROFILE_ID")
    if env and env.strip():
        return env.strip()
    return _DEFAULT_PROFILE_ID


def set_active_profile_id(profile_id: Optional[str]):
    """Set the active vertical for the current context (request/tenant). Returns a token; pass it
    to reset_active_profile_id() to restore. An empty/None id clears the override (→ env/default)."""
    return _ACTIVE_PROFILE_ID.set((str(profile_id).strip() or None) if profile_id else None)


def reset_active_profile_id(token) -> None:
    """Restore the previous active vertical (use the token from set_active_profile_id)."""
    try:
        _ACTIVE_PROFILE_ID.reset(token)
    except Exception:
        _ACTIVE_PROFILE_ID.set(None)


def clear_active_profile_id() -> None:
    """Hard-clear the override (→ env/default). Used by the test-isolation fixture."""
    _ACTIVE_PROFILE_ID.set(None)

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
def _load_profile(pid: str) -> Dict[str, Any]:
    """Load + validate ONE profile by its CONCRETE id (cached PER id — never by a dynamic
    default, so different verticals can't share a single cache entry).

    Strict mode (STORE_PROFILE_STRICT=1, set in CI/test) raises on malformed JSON / a missing
    non-default profile so a broken or mis-routed profile fails the build rather than silently
    degrading recommendations."""
    strict = str(os.getenv("STORE_PROFILE_STRICT", "0")).strip().lower() in ("1", "true", "yes")
    pid = (pid or _DEFAULT_PROFILE_ID).strip() or _DEFAULT_PROFILE_ID
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


def get_store_profile(profile_id: Optional[str] = None) -> Dict[str, Any]:
    """Load the StoreProfile for the ACTIVE vertical. Resolution: explicit ``profile_id`` →
    per-request ContextVar → STORE_PROFILE_ID env → electronics. Cached by the RESOLVED concrete
    id. No-arg callers (the common case) automatically get the active vertical — that is what
    makes the core tenant-aware without threading profile_id through every consumer."""
    return _load_profile(profile_id or active_profile_id())


def profile_slot(slot: str, *, profile_id: Optional[str] = None, default: Any = None) -> Any:
    """Read one slot from a profile with a default. The canonical accessor for excised
    flavour (e.g. brand_price_floors_usd) so call-sites never inline literals."""
    try:
        val = get_store_profile(profile_id).get(slot)
        return val if val is not None else default
    except Exception:
        return default


def brand_price_floors(profile_id: Optional[str] = None) -> Dict[str, int]:
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


def brand_label_patterns(profile_id: Optional[str] = None) -> Dict[str, list]:
    """Image→MANUFACTURER label patterns, DERIVED from the 3-axis `manufacturers` map
    ({mfr: lines + aliases}). This is the single source for the brand dicts that were
    scattered/duplicated across recommend.py. Falls back to a legacy flat
    `brand_label_patterns` slot if a profile predates the manufacturers schema."""
    mfrs = profile_slot("manufacturers", profile_id=profile_id, default=None)
    if isinstance(mfrs, dict) and mfrs:
        out: Dict[str, list] = {}
        for mfr, spec in mfrs.items():
            spec = spec if isinstance(spec, dict) else {}
            lines = [str(x).lower() for x in (spec.get("lines") or [])]
            aliases = [str(x).lower() for x in (spec.get("aliases") or [])]
            out[str(mfr).lower()] = lines + aliases
        return out
    legacy = profile_slot("brand_label_patterns", profile_id=profile_id, default=None)
    return legacy if isinstance(legacy, dict) else {}


def product_line_index(profile_id: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """token → {manufacturer, line} index, DERIVED from `manufacturers`. The new line-aware
    axis: lets the platform resolve a sub-brand/product-range token to its manufacturer + the
    line itself, independently of product TYPE — for brand-alias normalisation, identity, and
    line-aware upsell (a line-matched accessory for a line-matched primary item). An alias token
    maps to its manufacturer with line=None (it's the company, not a specific range)."""
    mfrs = profile_slot("manufacturers", profile_id=profile_id, default=None)
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(mfrs, dict):
        for mfr, spec in mfrs.items():
            spec = spec if isinstance(spec, dict) else {}
            m = str(mfr).lower()
            for line in (spec.get("lines") or []):
                out[str(line).lower()] = {"manufacturer": m, "line": str(line).lower()}
            for alias in (spec.get("aliases") or []):
                out.setdefault(str(alias).lower(), {"manufacturer": m, "line": None})
    return out


def reset_cache() -> None:
    """Clear the profile cache + the active-vertical override — MUST be called by the test
    isolation fixture so a profile loaded (or activated) under one tenant/vertical can't leak
    into the next test."""
    try:
        _load_profile.cache_clear()
    except Exception:
        pass
    try:
        clear_active_profile_id()
    except Exception:
        pass
