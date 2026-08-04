from __future__ import annotations

import re
from typing import Dict, Any
from src.app.config import load_feature_flags, get_settings
from src.app.feature_flags import get_flags as _ff_get_flags

# Lightweight anomaly detector scaffold for model-poison / DDOS-like signals.
# This is intentionally conservative and non-blocking; productions should
# replace with an online ML detector or Redis-based velocity checks.

try:
    _flags = _ff_get_flags()
except Exception:
    _flags = {}
_thr = (_flags or {}).get("SECURITY_THRESHOLDS", {})
_rep_min = int(float(_thr.get("ANOMALY_REPEAT_MIN", 50)))
_long_len = int(float(_thr.get("ANOMALY_LONG_TOKEN_LEN", 500)))
REPEATED_SEQ_PAT = re.compile(rf"(.)\1{{{_rep_min},}}")
LONG_TOKEN_PAT = re.compile(rf"[A-Za-z0-9+/]{{{_long_len},}}")


def detect_anomaly(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a small dict describing detected anomalies.

    Example return: {"anomaly": True, "severity": "high", "reason": "repeated_sequence"}
    """
    if not payload:
        return {"anomaly": False}
    try:
        body = ""
        if isinstance(payload, dict):
            # serialize a concise representation
            body = str(payload.get("body") or "")
        if not body:
            return {"anomaly": False}
        # High-confidence poison signals: extremely long repeated characters
        if REPEATED_SEQ_PAT.search(body):
            return {"anomaly": True, "severity": "high", "reason": "repeated_sequence"}
        # Suspicious long uninterrupted token (base64 or similar) could indicate payload stuffing
        if LONG_TOKEN_PAT.search(body):
            return {"anomaly": True, "severity": "medium", "reason": "long_token"}
        # default: no anomaly
        return {"anomaly": False}
    except Exception:
        return {"anomaly": False}
