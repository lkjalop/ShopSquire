from __future__ import annotations

import os
import re
from typing import Any, Dict, Tuple

_SECRET_PATTERNS = [
    re.compile(r"(?i)-----BEGIN (?:RSA|EC|OPENSSH|DSA)? ?PRIVATE KEY-----"),
    re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\b(?:xoxb|xoxp|xoxe|xoxa)-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"(?i)\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b"),
    re.compile(r"(?i)\b(?:sk|rk|pk)_(?:live|test)?_[A-Za-z0-9]{16,}\b"),
]


def _non_local_env() -> bool:
    env = str(os.getenv("APP_ENV", "local") or "local").strip().lower()
    return env not in ("local", "dev", "development", "test", "testing")


def dlp_scrub_text(value: str) -> Tuple[str, int]:
    text = str(value or "")
    hits = 0
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.search(out):
            hits += 1
            out = pat.sub("[REDACTED_SECRET]", out)
    return out, hits


def dlp_sanitize_export_value(value: Any) -> Tuple[Any, int]:
    if isinstance(value, str):
        return dlp_scrub_text(value)
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        total = 0
        for k, v in value.items():
            sv, h = dlp_sanitize_export_value(v)
            out[k] = sv
            total += h
        return out, total
    if isinstance(value, list):
        out = []
        total = 0
        for item in value:
            sv, h = dlp_sanitize_export_value(item)
            out.append(sv)
            total += h
        return out, total
    return value, 0


def dlp_sanitize_export_record(record: Dict[str, Any]) -> Dict[str, Any]:
    sanitized, hits = dlp_sanitize_export_value(record)
    if not isinstance(sanitized, dict):
        sanitized = {"value": sanitized}
    if hits > 0 and str(os.getenv("EXPORT_DLP_BLOCK_ON_SECRET", "1" if _non_local_env() else "0")).lower() in ("1", "true", "yes"):
        # Keep row shape stable while preventing leak.
        return {k: "[DLP_BLOCKED]" for k in sanitized.keys()}
    return sanitized
