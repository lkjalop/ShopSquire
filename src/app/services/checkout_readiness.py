"""Buyer-safe payment and shipping readiness without exposing credentials."""

from __future__ import annotations

import os
import re
from typing import Any

from src.app.config import get_settings
from src.app.services.shipping_providers import shipping_readiness


def _enabled(name: str, *, default: bool) -> bool:
    value = str(os.getenv(name, "") or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def buyer_checkout_readiness() -> dict[str, Any]:
    environment = str(os.getenv("APP_ENV", "local") or "local").lower()
    non_production = environment in {"local", "dev", "development", "test", "testing"}
    payment_execution = _enabled("PAYMENT_EXECUTION_ENABLED", default=non_production)
    demo_allowed = _enabled("ALLOW_DEMO_CHECKOUT", default=non_production)
    # Resolve validated application settings only when payment execution could use a provider.
    settings = get_settings() if payment_execution else None
    publishable_key = str(os.getenv("STRIPE_PUBLISHABLE_KEY", "") or "")
    secret_key = str(getattr(settings, "stripe_api_key", "") or "") if settings is not None else ""
    stripe_ready = (
        payment_execution
        and bool(re.match(r"^pk_(test|live)_[A-Za-z0-9]+$", publishable_key))
        and secret_key.startswith("sk_")
        and secret_key != "sk_test_xxx"
    )
    if stripe_ready:
        payment = {
            "status": "configured",
            "label": "Configured",
            "methods": ["stripe"],
            "real_payment": True,
            "reason": "Stripe payment is configured.",
        }
    elif demo_allowed:
        payment = {
            "status": "demo_only",
            "label": "Demo only",
            "methods": ["demo"],
            "real_payment": False,
            "reason": "No real payment is processed in this portfolio environment.",
        }
    else:
        payment = {
            "status": "unavailable",
            "label": "Unavailable",
            "methods": [],
            "real_payment": False,
            "reason": "No payment method is configured.",
        }

    carrier = shipping_readiness()
    shipping = {
        "status": "live_carrier_verified" if carrier.get("ready") else "estimated_plan_only",
        "label": "Live carrier verified" if carrier.get("ready") else "Estimated plan only",
        "provider": carrier.get("provider") if carrier.get("ready") else None,
        "reason": carrier.get("reason"),
    }
    return {"payment": payment, "shipping": shipping}
