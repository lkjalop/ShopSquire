"""Governed external evidence for named workloads.

The router may identify a name from unbounded language. This module never trusts that name
as a requirement: it resolves evidence through an enrolled connector, validates provenance,
and returns registry-shaped constraints for the shared fit engine.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse
from typing import Any, Dict, Iterable, Tuple


_STEAM_HOST = "store.steampowered.com"


def _enabled_flag() -> bool:
    override = os.getenv("STEAM_REQUIREMENTS_LIVE_ENABLED")
    if override is not None:
        return override.strip().lower() in ("1", "true", "yes", "on")
    try:
        from src.app.config import get_settings, load_feature_flags
        return bool(load_feature_flags(get_settings().feature_flags_path).get(
            "STEAM_REQUIREMENTS_LIVE_ENABLED", False))
    except Exception:
        return False


def _source_enrolled() -> bool:
    try:
        from src.app.platform.store_profile import profile_slot
        allowed = profile_slot("external_research_allowlist", default=[]) or []
    except Exception:
        return False
    for value in allowed:
        candidate = str(value or "").strip()
        host = (urlparse(candidate).hostname if "://" in candidate else candidate).lower()
        if host == _STEAM_HOST:
            return True
    return False


def live_steam_allowed(*, consent: bool) -> bool:
    """All three gates are mandatory: buyer consent, operator flag, enrolled source."""
    return bool(consent and _enabled_flag() and _source_enrolled())


def _minimum_constraints(requirements: Dict[str, Any]) -> Dict[str, Tuple[str, float]]:
    minimum = requirements.get("minimum") or {}
    out: Dict[str, Tuple[str, float]] = {}
    ram = minimum.get("ram_gb")
    storage = minimum.get("storage_gb")
    if isinstance(ram, (int, float)) and 1 <= float(ram) <= 512:
        out["ram_gb"] = (">=", float(ram))
    if isinstance(storage, (int, float)) and 1 <= float(storage) <= 8192:
        out["storage_gb"] = (">=", float(storage))
    try:
        from src.app.services.gpu_translation import desktop_req_to_laptop_tier
        translated = desktop_req_to_laptop_tier(str(minimum.get("gpu") or "")) or {}
        vram = translated.get("vram_gb_min")
        if isinstance(vram, (int, float)) and 0 <= float(vram) <= 128:
            out["gpu_vram_gb"] = (">=", float(vram))
    except Exception:
        pass
    return out


def resolve_named_games(entities: Iterable[Tuple[str, str]], *, consent: bool) -> Dict[str, Any]:
    """Resolve at most two clamped game names into minimum constraints and trace evidence."""
    from src.app.services.connectors.workload_evidence import default_registry

    allow_live = live_steam_allowed(consent=consent)
    registry = default_registry()
    requirements: Dict[str, Tuple[str, float]] = {}
    evidence = []
    seen = set()
    for kind, name in list(entities)[:3]:
        if kind != "game":
            continue
        key = str(name or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        typed = registry.resolve("game", name, allow_live=allow_live)
        result = typed.to_dict() if typed is not None else None
        if not result:
            evidence.append({
                "kind": "game", "requested_name": name, "status": "not_resolved",
                "live_allowed": allow_live,
            })
            continue
        for attr, predicate in _minimum_constraints(result).items():
            current = requirements.get(attr)
            if current is None or predicate[1] > current[1]:
                requirements[attr] = predicate
        evidence.append({
            "kind": "game",
            "requested_name": name,
            "resolved_name": result.get("title"),
            "status": "resolved",
            "source": result.get("source"),
            "source_url": result.get("source_url"),
            "retrieved_at": result.get("retrieved_at"),
            "cached": bool(result.get("cached")),
            "confidence": result.get("confidence"),
            "provenance_chain": list(result.get("provenance_chain") or []),
            "minimum": dict(result.get("minimum") or {}),
            "recommended": dict(result.get("recommended") or {}),
            "requested_target": dict(result.get("requested_target") or {}),
        })
        if len(evidence) >= 2:
            break
    return {"requirements": requirements, "evidence": evidence,
            "live_allowed": allow_live}
