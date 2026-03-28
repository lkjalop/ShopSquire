from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict


_DEFAULT_REGISTRY = Path("config/security/taxonomy/control_registry.json")


@lru_cache(maxsize=1)
def load_control_registry(path: str | None = None) -> Dict[str, Any]:
    candidate = Path(path or _DEFAULT_REGISTRY)
    try:
        if not candidate.exists() or not candidate.is_file():
            return {"version": None, "frameworks": {}}
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {"version": None, "frameworks": {}}
        payload.setdefault("frameworks", {})
        return payload
    except Exception:
        return {"version": None, "frameworks": {}}


def get_control_record(framework: str, control: str, *, path: str | None = None) -> Dict[str, Any]:
    registry = load_control_registry(path=path)
    frameworks = registry.get("frameworks") if isinstance(registry, dict) else {}
    if not isinstance(frameworks, dict):
        return {}
    rows = frameworks.get(str(framework)) if isinstance(frameworks, dict) else None
    if not isinstance(rows, dict):
        return {}
    row = rows.get(str(control))
    return dict(row) if isinstance(row, dict) else {}


def get_control_registry_version(path: str | None = None) -> str | None:
    registry = load_control_registry(path=path)
    version = registry.get("version") if isinstance(registry, dict) else None
    return str(version).strip() or None
