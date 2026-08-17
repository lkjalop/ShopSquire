"""Registration boundary for optional commerce background services."""
from __future__ import annotations

import importlib
import os
from typing import Callable

from fastapi import FastAPI


def _register_pair(
    app: FastAPI, *, name: str, start: Callable[[], object], stop: Callable[[], object],
) -> None:
    app.add_event_handler("startup", start)
    app.add_event_handler("shutdown", stop)
    current = list(getattr(app.state, "business_background_services", ()) or ())
    current.append(name)
    app.state.business_background_services = tuple(current)


def register_business_background_lifecycle(app: FastAPI) -> tuple[str, ...]:
    """Register optional services and retain explicit registration truth."""
    app.state.business_background_services = ()
    failures: dict[str, str] = {}
    definitions = (
        ("retention", "src.app.services.retention", "start_retention_loop", "stop_retention_loop"),
        ("incident_sla", "src.app.services.incident_sla_scheduler", "start_incident_sla_scheduler", "stop_incident_sla_scheduler"),
        ("payment_reconcile", "src.app.services.payment_reconcile_scheduler", "start_payment_reconcile_scheduler", "stop_payment_reconcile_scheduler"),
    )
    for name, module_name, start_name, stop_name in definitions:
        try:
            module = importlib.import_module(module_name)
            start_fn = getattr(module, start_name)
            stop_fn = getattr(module, stop_name)
            _register_pair(
                app, name=name,
                start=lambda fn=start_fn: fn(app),
                stop=lambda fn=stop_fn: fn(app),
            )
        except Exception as exc:
            failures[name] = type(exc).__name__
    if str(os.getenv("WEBHOOK_DISPATCHER_WORKER_ENABLED", "1")).lower() in {
        "1", "true", "yes",
    }:
        try:
            module = importlib.import_module("src.app.services.webhook_dispatcher")
            _register_pair(
                app, name="webhook_dispatcher",
                start=lambda: module.start_worker(app),
                stop=module.stop_worker,
            )
        except Exception as exc:
            failures["webhook_dispatcher"] = type(exc).__name__
    app.state.business_background_lifecycle = {
        "registered": tuple(app.state.business_background_services),
        "optional_failures": failures,
    }
    return tuple(app.state.business_background_services)


__all__ = ["register_business_background_lifecycle"]
