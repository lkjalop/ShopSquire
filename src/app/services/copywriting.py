from __future__ import annotations

import os
import re
import time
from typing import Any, Dict


_DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
    "balanced": {
        "tone": "balanced",
        "cta": "Want me to narrow this by budget or use case?",
        "max_chars": 420,
    },
    "premium": {
        "tone": "premium",
        "cta": "Want a premium shortlist with the fastest shipping options?",
        "max_chars": 420,
    },
    "playful": {
        "tone": "playful",
        "cta": "Want me to pull a quick top-picks list next?",
        "max_chars": 380,
    },
    "technical": {
        "tone": "technical",
        "cta": "Want this filtered by exact specs and price ceiling?",
        "max_chars": 500,
    },
}


def _env_bool(name: str, default: str = "0") -> bool:
    return str(os.getenv(name, default)).strip().lower() in ("1", "true", "yes", "on")


def _resolve_profile(profile_id: str | None, inline_profile: Dict[str, Any] | None) -> tuple[str, Dict[str, Any]]:
    pid = str(profile_id or "balanced").strip().lower() or "balanced"
    base = dict(_DEFAULT_PROFILES.get(pid) or _DEFAULT_PROFILES["balanced"])
    if isinstance(inline_profile, dict):
        for k in ("tone", "cta", "max_chars"):
            if inline_profile.get(k) is not None:
                base[k] = inline_profile.get(k)
    return pid, base


def _strip_risky_marketing_claims(text: str) -> str:
    out = str(text or "")
    out = re.sub(r"\b(guaranteed|guarantee|risk[- ]?free|always best)\b", "verified", out, flags=re.I)
    out = re.sub(r"\b(cheapest|best ever|perfect)\b", "strong", out, flags=re.I)
    return out


def _compress_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def maybe_apply_copywriting(
    *,
    assistant_message: str | None,
    turn_intent: str | None,
    surface: str | None = None,
    requested_enabled: bool | None = None,
    profile_id: str | None = None,
    inline_profile: Dict[str, Any] | None = None,
    brand_name: str | None = None,
) -> Dict[str, Any]:
    t0 = time.perf_counter()
    msg = str(assistant_message or "").strip()
    intent = str(turn_intent or "SEARCH").upper()
    surface_eff = str(surface or "storefront").strip().lower() or "storefront"
    global_enabled = _env_bool("COPYWRITING_ENABLED", "0")
    requested = requested_enabled is True
    enabled = bool(requested or global_enabled)

    allowed_surfaces = {
        s.strip().lower()
        for s in str(os.getenv("COPYWRITING_ALLOWED_SURFACES", "storefront,landing,email")).split(",")
        if s.strip()
    }
    if not msg:
        return {
            "assistant_message": msg,
            "meta": {
                "applied": False,
                "reason": "empty_message",
                "requested": requested,
                "enabled": enabled,
                "surface": surface_eff,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            },
        }
    if not enabled:
        return {
            "assistant_message": msg,
            "meta": {
                "applied": False,
                "reason": "disabled",
                "requested": requested,
                "enabled": enabled,
                "surface": surface_eff,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            },
        }
    if surface_eff not in allowed_surfaces:
        return {
            "assistant_message": msg,
            "meta": {
                "applied": False,
                "reason": "surface_not_allowed",
                "requested": requested,
                "enabled": enabled,
                "surface": surface_eff,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            },
        }
    if intent == "SUPPORT_CLAIM" and not _env_bool("COPYWRITING_ENABLE_SUPPORT", "0"):
        return {
            "assistant_message": msg,
            "meta": {
                "applied": False,
                "reason": "support_intent_skipped",
                "requested": requested,
                "enabled": enabled,
                "surface": surface_eff,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
            },
        }

    pid, profile = _resolve_profile(profile_id, inline_profile)
    tone = str(profile.get("tone") or "balanced").strip().lower()
    cta = str(profile.get("cta") or "").strip()
    max_chars = int(profile.get("max_chars") or os.getenv("COPYWRITING_MAX_CHARS", "420") or 420)
    max_chars = max(160, min(max_chars, 900))

    rewritten = msg
    if tone == "premium":
        rewritten = f"Curated for quality. {rewritten}"
    elif tone == "playful":
        rewritten = f"Nice pick. {rewritten}"
    elif tone == "technical":
        rewritten = f"Spec-oriented summary: {rewritten}"

    bname = str(brand_name or "").strip()
    if bname:
        rewritten = f"{bname}: {rewritten}"

    if cta and intent in {"SEARCH", "FILTER", "COMPARE"}:
        if not rewritten.endswith((".", "!", "?")):
            rewritten = f"{rewritten}."
        rewritten = f"{rewritten} {cta}"

    before_policy = rewritten
    rewritten = _strip_risky_marketing_claims(_compress_whitespace(rewritten))
    policy_gate_triggered = rewritten != before_policy
    if len(rewritten) > max_chars:
        rewritten = rewritten[: max_chars - 1].rstrip() + "…"

    return {
        "assistant_message": rewritten,
        "meta": {
            "applied": rewritten != msg,
            "mode": "deterministic_rules_v1",
            "profile_id": pid,
            "tone": tone,
            "surface": surface_eff,
            "requested": requested,
            "enabled": enabled,
            "cpu_cost": "low",
            "policy_gate_triggered": policy_gate_triggered,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
        },
    }
