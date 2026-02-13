import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Any, List, Tuple


@dataclass
class CalibrationSpec:
    method: str
    params: Dict[str, Any]


def _default_path() -> str:
    return os.getenv("CONFIDENCE_CALIBRATION_PATH", "config/confidence_calibration.json")


@lru_cache(maxsize=4)
def _load_calibration(path: str) -> Dict[str, CalibrationSpec]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, CalibrationSpec] = {}
    for key, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        method = str(spec.get("method") or "identity").lower()
        params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
        if method == "isotonic":
            pts = spec.get("points") if isinstance(spec.get("points"), list) else []
            params = {"points": _normalize_points(pts)}
        out[key] = CalibrationSpec(method=method, params=params)
    return out


def _normalize_points(points: List) -> List[Tuple[float, float]]:
    clean: List[Tuple[float, float]] = []
    for p in points:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            continue
        try:
            x = float(p[0])
            y = float(p[1])
        except Exception:
            continue
        clean.append((x, y))
    clean.sort(key=lambda t: t[0])
    return clean


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _apply_platt(x: float, a: float, b: float) -> float:
    import math
    try:
        return 1.0 / (1.0 + math.exp(-(a * x + b)))
    except Exception:
        return x


def _apply_isotonic(x: float, points: List[Tuple[float, float]]) -> float:
    if not points:
        return x
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return x


def calibrate_confidence(raw: float, agent_type: str | None = None) -> float:
    path = _default_path()
    specs = _load_calibration(path)
    spec = specs.get(agent_type or "") or specs.get("default")
    if not spec:
        return _clamp01(float(raw))
    method = spec.method
    params = spec.params or {}
    val = float(raw)
    if method == "platt":
        a = float(params.get("a", 1.0))
        b = float(params.get("b", 0.0))
        return _clamp01(_apply_platt(val, a, b))
    if method == "isotonic":
        pts = params.get("points") if isinstance(params.get("points"), list) else []
        return _clamp01(_apply_isotonic(val, pts))
    return _clamp01(val)

