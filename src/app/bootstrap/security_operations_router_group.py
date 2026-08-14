"""Email, artifact-security, and governed operations router boundary."""

from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI


_OPTIONAL_ROUTERS = (
    ("email_security_admin", "src.app.routers.email_security_admin"),
    ("email_security", "src.app.routers.email_security"),
    ("gmail_ingest", "src.app.routers.ingest_gmail"),
    ("m365_ingest", "src.app.routers.ingest_m365"),
    ("admin_email_security", "src.app.routers.admin_email_security"),
    ("admin_playbooks", "src.app.routers.admin_playbooks"),
    ("admin_storage", "src.app.routers.admin_storage"),
    ("admin_grafana_proxy", "src.app.routers.admin_grafana_proxy"),
    ("admin_email", "src.app.routers.admin_email"),
    ("outbound_email_quarantine", "src.app.routers.outbound_email_quarantine"),
)


def register_security_operations_router_group(app: FastAPI) -> tuple[str, ...]:
    """Register optional security surfaces without hiding their readiness state."""

    registered: list[str] = []
    failed: list[str] = []
    log = logging.getLogger("shopsquire.startup")
    for name, module_name in _OPTIONAL_ROUTERS:
        try:
            module = importlib.import_module(module_name)
            app.include_router(module.router)
            registered.append(name)
        except Exception as exc:
            failed.append(name)
            log.exception("failed to include %s router: %s", name, exc)
    app.state.security_operations_router_group = tuple(registered)
    app.state.security_operations_router_failures = tuple(failed)
    return tuple(registered)


__all__ = ["register_security_operations_router_group"]
