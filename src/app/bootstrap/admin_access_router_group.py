"""Administrative identity, connector, and decision-audit route composition."""
from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

from src.app.routers.admin import router as admin_router


OPTIONAL_ADMIN_ACCESS_ROUTERS = (
    ("admin_mfa", "src.app.routers.admin_mfa_routes"),
    ("admin_api_keys", "src.app.routers.admin_api_keys"),
    ("connectors_auth", "src.app.routers.connectors_auth"),
    ("connectors_admin", "src.app.routers.connectors_admin"),
    ("case_cockpit", "src.app.routers.case_cockpit"),
    ("decision_time_travel", "src.app.routers.decision_time_travel"),
    ("authz_audit", "src.app.routers.authz_audit"),
)


def register_admin_access_router_group(app: FastAPI) -> tuple[str, ...]:
    registered = ["admin"]
    failures: dict[str, str] = {}
    app.include_router(admin_router)
    log = logging.getLogger("shopsquire.startup")
    for name, module_name in OPTIONAL_ADMIN_ACCESS_ROUTERS:
        try:
            module = importlib.import_module(module_name)
            app.include_router(module.router)
            registered.append(name)
        except Exception as exc:
            failures[name] = type(exc).__name__
            log.exception("failed to include %s router: %s", name, exc)
    app.state.admin_access_router_group = {
        "registered": tuple(registered),
        "optional_failures": failures,
    }
    return tuple(registered)


__all__ = ["OPTIONAL_ADMIN_ACCESS_ROUTERS", "register_admin_access_router_group"]
