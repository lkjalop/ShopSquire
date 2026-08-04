from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from src.app.rules.tenant_config_store import TenantConfigStore


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")) or {})
    except Exception:
        return {}


def _merge(base: Dict[str, Any], override: Dict[str, Any] | None) -> Dict[str, Any]:
    if not override:
        return dict(base or {})
    out = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out.get(k, {}), v)
        else:
            out[k] = v
    return out


@lru_cache(maxsize=1)
def _tenant_store() -> TenantConfigStore:
    return TenantConfigStore(cache_ttl=10)


@lru_cache(maxsize=1)
def _eligibility_base() -> Dict[str, Any]:
    p = Path(os.getenv("ELIGIBILITY_RULES_PATH", "config/rules/eligibility_policies.json")).resolve()
    return _read_json(p) if p.exists() else {}


def eligibility_defaults(*, tenant_id: str | None = None) -> Dict[str, Any]:
    base = _eligibility_base()
    try:
        override = _tenant_store().get_override("eligibility_policies", tenant_id=tenant_id)
    except Exception:
        override = None
    return _merge(base, override)


@lru_cache(maxsize=1)
def _image_quality_base() -> Dict[str, Any]:
    p = Path(os.getenv("IMAGE_QUALITY_RULES_PATH", "config/rules/image_quality_thresholds.json")).resolve()
    return _read_json(p) if p.exists() else {}


def image_quality_defaults(*, tenant_id: str | None = None) -> Dict[str, Any]:
    base = _image_quality_base()
    try:
        override = _tenant_store().get_override("image_quality_thresholds", tenant_id=tenant_id)
    except Exception:
        override = None
    return _merge(base, override)


def fraud_heuristics_defaults(*, tenant_id: str | None = None) -> Dict[str, Any]:
    p = Path(os.getenv("FRAUD_HEURISTICS_PATH", "config/rules/fraud_heuristics.json")).resolve()
    base = _read_json(p) if p.exists() else {}
    try:
        override = _tenant_store().get_override("fraud_heuristics", tenant_id=tenant_id)
    except Exception:
        override = None
    return _merge(base, override)


def escalation_triggers_defaults(*, tenant_id: str | None = None) -> Dict[str, Any]:
    p = Path(os.getenv("ESCALATION_TRIGGERS_PATH", "config/rules/escalation_triggers.json")).resolve()
    base = _read_json(p) if p.exists() else {}
    try:
        override = _tenant_store().get_override("escalation_triggers", tenant_id=tenant_id)
    except Exception:
        override = None
    return _merge(base, override)


def serial_patterns_defaults(*, tenant_id: str | None = None) -> Dict[str, Any]:
    p = Path(os.getenv("SERIAL_PATTERNS_PATH", "config/rules/serial_patterns.json")).resolve()
    base = _read_json(p) if p.exists() else {}
    try:
        override = _tenant_store().get_override("serial_patterns", tenant_id=tenant_id)
    except Exception:
        override = None
    return _merge(base, override)


def returns_policy_defaults(*, tenant_id: str | None = None) -> Dict[str, Any]:
    p = Path(os.getenv("RETURNS_POLICY_PATH", "config/rules/returns_policy.json")).resolve()
    base = _read_json(p) if p.exists() else {}
    try:
        override = _tenant_store().get_override("returns_policy", tenant_id=tenant_id)
    except Exception:
        override = None
    return _merge(base, override)
