"""Truthful runtime-mode reporting for health and readiness probes."""
from __future__ import annotations

import os
from typing import Any


_TRUE = {"1", "true", "yes", "on"}


def _enabled(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in _TRUE


def _mode(name: str, default: str = "off") -> str:
    return str(os.getenv(name, default) or default).strip().lower()


def runtime_mode_snapshot() -> dict[str, Any]:
    """Return declared profile, active lane modes, and any profile mismatch.

    ``standard`` imposes no recommendation-profile readiness requirements.
    Deployments that advertise ``demo_v2`` must actually enable the bounded
    core, confirmation-gated cart lane, and read-only procurement advice.
    """
    profile = _mode("SHOPSQUIRE_RUNTIME_PROFILE", "standard")
    active = {
        "recommendation_core": _mode("RECOMMEND_CORE_MODE"),
        "cart_mutation": "on" if _enabled("RECOMMEND_CART_SERVE") else "off",
        "procurement_advice": _mode("RECOMMEND_PROCUREMENT_ADVICE_MODE"),
        "policy_answers": _mode("RECOMMEND_POLICY_ANSWER_MODE"),
        "support_handoff": _mode("RECOMMEND_SUPPORT_HANDOFF_MODE"),
        "inventory_read": _mode("RECOMMEND_INVENTORY_READ_MODE"),
        "compatibility_cutover": (
            "on"
            if _mode(
                "RECOMMEND_COMPATIBILITY_CUTOVER_ENABLED",
                _mode("RECOMMEND_LEGACY_DELEGATE_ENABLED", "1"),
            ) in _TRUE
            else "off"
        ),
        "supplier_transport": _mode("FULFILLMENT_SUPPLIER_TRANSPORT", "unset"),
        "supplier_autonomy": "on" if _enabled("FULFILLMENT_AUTONOMOUS_SEND") else "off",
        "image_authority": _mode("IMAGE_RECOMMENDATION_MODE", "canonical"),
    }
    mismatches: list[dict[str, str]] = []
    if profile == "demo_v2":
        required = {
            "recommendation_core": {"primary"},
            "cart_mutation": {"on"},
            "procurement_advice": {"on"},
            "policy_answers": {"on"},
            "support_handoff": {"on"},
            "inventory_read": {"on"},
            "compatibility_cutover": {"on"},
        }
        for key, allowed in required.items():
            actual = active[key]
            if actual not in allowed:
                mismatches.append({
                    "mode": key,
                    "expected": "|".join(sorted(allowed)),
                    "actual": actual,
                })
    rollback = {
        "behavior": (
            "v2_compatibility"
            if active["compatibility_cutover"] == "on"
            else "bounded_unavailable"
        ),
        "available": True,
        "equivalence_observed": False,
        "reason": (
            "v2_compatibility_cutover_enabled"
            if active["compatibility_cutover"] == "on"
            else "compatibility_cutover_disabled"
        ),
    }
    return {
        "profile": profile,
        "ready": not mismatches,
        "active": active,
        "mismatches": mismatches,
        "rollback": rollback,
    }
