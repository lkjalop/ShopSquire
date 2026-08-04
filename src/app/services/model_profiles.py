"""Model descriptors — per-model operating physics + certified roles (agnostic core).

Why (the seven-layer-mute lesson, bb4cd0a): the platform hardcoded ONE model's latency profile
into its timeouts (8s narration cap, 25s inner summary timeout, think-mode auto) and every model
that breathed differently had its prose silently discarded — the platform looked "dumb" for
months while the answers were being thrown away. A BYO-model platform cannot hardcode any
model's physics: they live in `config/model_profiles.json`, measured by the A/B/certification
harness, and every consumer resolves env override (ops) -> descriptor -> conservative fallback.

The descriptor is also the certification artifact: `certified_roles` says which pipeline jobs
(narrator / planner / binder / knowledge) a model passed cert for, and `resident_footprint_gb`
lets deployment certify the RESIDENT SET against the GPU budget (round 4: two individually-fine
12-14B models are jointly unrunnable on 12GB — swap-thrash).
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, Optional

_PATH = os.path.join("config", "model_profiles.json")
_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None


def _profiles() -> Dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            try:
                with open(_PATH, encoding="utf-8") as f:
                    _cache = json.load(f)
            except Exception:
                _cache = {}
        return _cache


def model_profile(model: Optional[str]) -> Dict[str, Any]:
    """Descriptor for a model: exact tag match, then family match ('qwen3' covers
    'qwen3:8b'), then _default. Always returns a dict (never raises)."""
    profs = _profiles()
    base = dict(profs.get("_default") or {})
    name = str(model or "").strip().lower()
    hit = None
    if name:
        for key, val in profs.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            if key.lower() == name:
                hit = val
                break
        if hit is None:
            fam = name.split(":", 1)[0]
            for key, val in profs.items():
                if key.startswith("_") or not isinstance(val, dict):
                    continue
                if key.lower().split(":", 1)[0] == fam:
                    hit = val
                    break
    if hit:
        base.update(hit)
    return base


def _env_float(var: str) -> Optional[float]:
    raw = os.getenv(var)
    if raw is None or not str(raw).strip():
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def summary_timeout_s(model: Optional[str], fallback: float = 25.0) -> float:
    """Inner LLM-call timeout for summaries/knowledge: env OLLAMA_SUMMARY_TIMEOUT_S wins,
    else the model descriptor, else the conservative fallback (was mute-layer 6)."""
    env = _env_float("OLLAMA_SUMMARY_TIMEOUT_S")
    if env is not None:
        return env
    try:
        return float(model_profile(model).get("summary_timeout_s") or fallback)
    except (TypeError, ValueError):
        return fallback


def narration_timeout_s(model: Optional[str], fallback: float = 8.0) -> float:
    """Blocking-narration wall clock: env RECOMMEND_NARRATION_TIMEOUT_SEC wins, else the
    model descriptor, else the historical 8s (was mute-layer 3 — 8s < every model's think)."""
    env = _env_float("RECOMMEND_NARRATION_TIMEOUT_SEC")
    if env is not None:
        return env
    try:
        return float(model_profile(model).get("narration_timeout_s") or fallback)
    except (TypeError, ValueError):
        return fallback


def think_mode(model: Optional[str]) -> str:
    """Summary think-mode: env OLLAMA_SUMMARY_THINK wins, else the model descriptor,
    else 'auto' (the historical default; auto fires on enough/why/compare wording)."""
    env = os.getenv("OLLAMA_SUMMARY_THINK")
    if env is not None and str(env).strip():
        return str(env).strip().lower()
    return str(model_profile(model).get("think_mode") or "auto").strip().lower()
