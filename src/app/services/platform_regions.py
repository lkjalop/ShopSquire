from __future__ import annotations

import json
import os
from typing import Any, Dict, List


def _default_topology() -> Dict[str, Any]:
    return {
        "primary_region": "us-east-1",
        "regions": [
            {"id": "us-east-1", "role": "primary", "active": True},
            {"id": "us-west-2", "role": "replica", "active": False},
        ],
        "data_residency_mode": "single_region",
        "replication_mode": "none",
    }


def load_region_topology() -> Dict[str, Any]:
    path = str(os.getenv("PLATFORM_REGIONS_PATH", "config/platform_regions.json") or "").strip()
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return _default_topology()


def region_readiness() -> Dict[str, Any]:
    topo = load_region_topology()
    regions = topo.get("regions") if isinstance(topo.get("regions"), list) else []
    active = [r for r in regions if isinstance(r, dict) and bool(r.get("active"))]
    primary = str(topo.get("primary_region") or "").strip()
    primary_present = any(str((r or {}).get("id") or "").strip() == primary for r in regions)
    return {
        "primary_region": primary or None,
        "regions": regions,
        "active_regions": len(active),
        "multi_region_ready": bool(primary_present and len(active) >= 2),
        "data_residency_mode": str(topo.get("data_residency_mode") or "single_region"),
        "replication_mode": str(topo.get("replication_mode") or "none"),
    }

