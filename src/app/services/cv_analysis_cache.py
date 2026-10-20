"""Scope cached image analysis to its request and detector policy."""
import hashlib
import json
import os
from typing import Any

from src.app.platform.tenant_context import current_tenant_id


def analysis_namespace(*, meta: dict[str, Any] | None, pack: dict[str, Any]) -> str:
    context = {
        "tenant_id": current_tenant_id(),
        "meta": meta or {},
        "pack": pack,
        "configuration": {key: value for key, value in os.environ.items() if key.startswith("CV_")},
    }
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded) > 65536:
        raise ValueError("tier2_cache_context_too_large")
    return "tier2-context-v1:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def is_cacheable_analysis(result: dict[str, Any]) -> bool:
    """Retry partial detector failures; bound inspection of nested results."""
    pending, visited = [result], set()
    while pending:
        value = pending.pop()
        if not isinstance(value, (dict, list, tuple)) or id(value) in visited:
            continue
        visited.add(id(value))
        if len(visited) > 4096:
            return False
        if isinstance(value, dict):
            if value.get("error"):
                return False
            pending.extend(value.values())
        else:
            pending.extend(value)
    return True
