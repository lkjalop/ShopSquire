from __future__ import annotations

import json
import os
from typing import Any, Dict

from src.app.cv.model_registry import enforce_pack_with_registry


def _load_packs() -> Dict[str, Any]:
    path = os.getenv("CV_MODEL_PACK_PATH") or os.path.join("config", "cv_model_packs.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"default": "agnostic_v1", "packs": {}}


def get_model_pack(pack_id: str | None = None, *, tenant_id: str | None = None) -> Dict[str, Any]:
    cfg = _load_packs()
    packs = cfg.get("packs") if isinstance(cfg.get("packs"), dict) else {}
    default_id = cfg.get("default") or "agnostic_v1"
    selected = pack_id or os.getenv("CV_MODEL_PACK") or default_id
    pack = packs.get(selected)
    if not pack:
        pack = packs.get(default_id) or {}
    out = {"id": selected, **(pack or {})}
    try:
        out = enforce_pack_with_registry(out, tenant_id=tenant_id)
    except Exception:
        pass
    return out


def get_all_model_packs() -> Dict[str, Any]:
    return _load_packs()
