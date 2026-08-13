"""Buyer storefront, payment-readiness, and post-order router registration."""
from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

from src.app.bootstrap.router_registration import RequiredRouter, register_required_routers
from src.app.routers import events, inventory, payments, pricing, support
from src.app.routers.payments_afterpay import router as payments_afterpay_router
from src.app.routers.payments_googlepay import router as payments_googlepay_router
from src.app.routers.payments_paypal import router as payments_paypal_router
from src.app.routers.payments_revolut import router as payments_revolut_router


STOREFRONT_ROUTER_GROUP = (
    RequiredRouter("pricing", pricing.router),
    RequiredRouter("inventory", inventory.router),
    RequiredRouter("support", support.router),
    RequiredRouter("events", events.router),
    RequiredRouter("payments", payments.router),
    RequiredRouter("payments_paypal", payments_paypal_router),
    RequiredRouter("payments_revolut", payments_revolut_router),
    RequiredRouter("payments_googlepay", payments_googlepay_router),
    RequiredRouter("payments_afterpay", payments_afterpay_router),
)


def register_storefront_router_group(app: FastAPI) -> tuple[str, ...]:
    registered = list(register_required_routers(app, STOREFRONT_ROUTER_GROUP))
    log = logging.getLogger("shopsquire.startup")
    for name, module_name in (
        ("returns", "src.app.routers.returns"),
        ("fraud", "src.app.routers.fraud"),
    ):
        try:
            app.include_router(getattr(importlib.import_module(module_name), "router"))
            registered.append(name)
        except Exception as exc:
            log.exception("failed to include optional %s router: %s", name, exc)
    app.state.storefront_router_group = tuple(registered)
    return tuple(registered)


__all__ = ["STOREFRONT_ROUTER_GROUP", "register_storefront_router_group"]
