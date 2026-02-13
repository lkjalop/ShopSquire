from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Optional

from src.app.rules.tenant_config_store import TenantConfigStore


def _registry_path() -> str:
    return os.getenv("CV_MODEL_REGISTRY_PATH") or os.path.join("config", "cv", "model_registry.json")


@lru_cache(maxsize=1)
def _load_registry_file() -> Dict[str, Any]:
    path = _registry_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out.get(k) or {}, v)
        else:
            out[k] = v
    return out


def get_cv_model_registry(*, tenant_id: str | None = None, store: Optional[TenantConfigStore] = None) -> Dict[str, Any]:
    """Return the effective CV model registry for a tenant.

    Base config: `config/cv/model_registry.json`
    Tenant overrides (optional): `tenant_config_overrides` under key `cv_model_registry`.
    """
    base = _load_registry_file()
    default = base.get("default") if isinstance(base.get("default"), dict) else {}
    tenant_map = base.get("tenants") if isinstance(base.get("tenants"), dict) else {}
    per_tenant = tenant_map.get(str(tenant_id)) if tenant_id is not None else None
    per_tenant = per_tenant if isinstance(per_tenant, dict) else {}

    override = {}
    try:
        store = store or TenantConfigStore(cache_ttl=10)
        override = store.get_override("cv_model_registry", tenant_id=tenant_id) or {}
    except Exception:
        override = {}
    if not isinstance(override, dict):
        override = {}

    effective = _deep_merge(default, per_tenant)
    effective = _deep_merge(effective, override)

    # Normalize booleans/strings
    try:
        effective["enabled"] = bool(effective.get("enabled", True))
    except Exception:
        effective["enabled"] = True

    return effective


def enforce_pack_with_registry(pack: Dict[str, Any], *, tenant_id: str | None = None) -> Dict[str, Any]:
    """Return a sanitized model-pack dict based on the model registry."""
    out = dict(pack or {})
    reg = get_cv_model_registry(tenant_id=tenant_id)
    if not reg.get("enabled", True):
        # Disable both ROI and OCR deterministically.
        out["detector"] = {**(out.get("detector") or {}), "model": None, "enabled": False}
        out["ocr"] = {**(out.get("ocr") or {}), "provider": "disabled", "fallback": None, "enabled": False}
        return out

    det = out.get("detector") if isinstance(out.get("detector"), dict) else {}
    det_reg = reg.get("detector") if isinstance(reg.get("detector"), dict) else {}
    if not bool(det_reg.get("enabled", True)):
        out["detector"] = {**det, "model": None, "enabled": False}
    else:
        allowed = det_reg.get("allowed_models") if isinstance(det_reg.get("allowed_models"), list) else None
        model = det.get("model")
        if allowed and model and str(model) not in {str(a) for a in allowed if a}:
            out["detector"] = {**det, "model": None, "enabled": False, "disabled_reason": "model_not_allowed"}

    ocr = out.get("ocr") if isinstance(out.get("ocr"), dict) else {}
    ocr_reg = reg.get("ocr") if isinstance(reg.get("ocr"), dict) else {}
    if not bool(ocr_reg.get("enabled", True)):
        out["ocr"] = {**ocr, "provider": "disabled", "fallback": None, "enabled": False}
    else:
        allowed_p = ocr_reg.get("allowed_providers") if isinstance(ocr_reg.get("allowed_providers"), list) else None
        prov = (ocr.get("provider") or ocr_reg.get("default_provider") or "tesseract")
        fb = ocr.get("fallback") if "fallback" in ocr else ocr_reg.get("fallback_provider")
        if allowed_p and str(prov).lower() not in {str(a).lower() for a in allowed_p if a}:
            prov = "disabled"
        if allowed_p and fb and str(fb).lower() not in {str(a).lower() for a in allowed_p if a}:
            fb = None
        out["ocr"] = {**ocr, "provider": prov, "fallback": fb, "enabled": True}

    return out

