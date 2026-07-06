"""Cart age / time-to-live classification — pure, vertical-agnostic.

The cart records ``updated_at`` (bumped on every mutation), so ``now - updated_at`` is the time since the
buyer last touched the cart — the honest "delta from last interaction". This module turns that delta into
a tier + a human label so the UI can say "3 items, last touched ~4h ago" instead of guessing "previous
session" from a frontend snapshot (the guess that mislabeled a just-added cart in the demo).

No product vocabulary lives here — it is time arithmetic only, so it stays agnostic-core clean. The same
windows drive the retention sweeper (see config/retention_policy.json); erasure is a separate mechanism
(routers/privacy.py) and this module never deletes anything — it only labels.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_DEFAULT_FRESH_MAX_S = 3600      # < 1h  -> same active working session
_DEFAULT_WARM_MAX_S = 28800      # < 8h  -> carried from earlier, keep + offer clear
# >= warm_max            -> stale, suggest clear (still human-triggered / undoable)

_CONFIG_PATH = os.path.join("config", "retention_policy.json")
_CONFIG_CACHE: Optional[Dict[str, Any]] = None


def _load_config() -> Dict[str, Any]:
    """Load retention_policy.json once; fall back to defaults if absent or malformed (never raise)."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE
    cfg: Dict[str, Any] = {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
            if isinstance(loaded, dict):
                cfg = loaded
    except FileNotFoundError:
        cfg = {}
    except (json.JSONDecodeError, OSError, ValueError):
        cfg = {}
    _CONFIG_CACHE = cfg
    return cfg


def _tier_bounds() -> tuple[int, int]:
    tiers = _load_config().get("cart_age_tiers") or {}
    fresh = int(tiers.get("fresh_max_seconds", _DEFAULT_FRESH_MAX_S) or _DEFAULT_FRESH_MAX_S)
    warm = int(tiers.get("warm_max_seconds", _DEFAULT_WARM_MAX_S) or _DEFAULT_WARM_MAX_S)
    if warm < fresh:                     # guard a mis-edited config: warm must be >= fresh
        warm = fresh
    return fresh, warm


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse a SQL/ISO timestamp to naive-UTC. Handles SQLite 'YYYY-MM-DD HH:MM:SS', ISO 'T', and tz
    offsets / 'Z'. Returns None on anything unparseable (caller treats as unknown age, not an error)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        s = s.replace("Z", "+00:00")
        candidate = s.replace(" ", "T", 1) if "T" not in s else s
        dt = None
        try:
            dt = datetime.fromisoformat(candidate)
        except ValueError:
            base = s.split("+", 1)[0].split(".", 1)[0].replace("T", " ").strip()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
                try:
                    dt = datetime.strptime(base, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def idle_seconds(updated_at: Any, now: Optional[datetime] = None) -> Optional[float]:
    """Seconds since the cart was last touched. None if the timestamp is missing/unparseable.

    Clamped at 0 so mild clock skew (a timestamp a hair in the future) never reports a negative age."""
    dt = parse_timestamp(updated_at)
    if dt is None:
        return None
    reference = now or datetime.utcnow()
    return max(0.0, (reference - dt).total_seconds())


def humanize_idle(seconds: Optional[float]) -> str:
    """Coarse, buyer-friendly age label: 'just now', '~40 min ago', '~4 hours ago', 'yesterday'."""
    if seconds is None:
        return ""
    s = int(max(0.0, seconds))
    if s < 90:
        return "just now"
    if s < 3600:
        return f"~{s // 60} min ago"
    if s < 86400:
        hours = int(round(s / 3600.0))
        return f"~{hours} hour{'s' if hours != 1 else ''} ago"
    days = s // 86400
    if days == 1:
        return "yesterday"
    return f"~{days} days ago"


def classify_cart_age(idle_s: Optional[float], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Classify a cart's idle delta into a tier + label the UI can trust.

    - fresh  (< fresh_max): same working session — do not nag.
    - warm   (fresh_max..warm_max): carried from earlier — keep, label it, offer clear.
    - stale  (>= warm_max): predates this session — suggest clear (still human-triggered + undoable).
    - unknown: no timestamp — behave conservatively (not carried, no suggestion).

    ``now`` is accepted for deterministic tests. Pure: no I/O beyond the cached config, never raises.
    """
    if idle_s is None:
        return {"tier": "unknown", "idle_seconds": None, "label": "", "is_carried": False, "suggest_clear": False}
    fresh_max, warm_max = _tier_bounds()
    if idle_s < fresh_max:
        tier = "fresh"
    elif idle_s < warm_max:
        tier = "warm"
    else:
        tier = "stale"
    return {
        "tier": tier,
        "idle_seconds": int(idle_s),
        "label": humanize_idle(idle_s),
        "is_carried": tier in ("warm", "stale"),
        "suggest_clear": tier == "stale",
    }


def classify_updated_at(updated_at: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Convenience: raw ``updated_at`` timestamp -> full age block (idle + tier + label)."""
    return classify_cart_age(idle_seconds(updated_at, now=now), now=now)
