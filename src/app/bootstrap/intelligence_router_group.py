"""Decision-memory and buyer-signal router registration boundary."""
from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

from src.app.routers.session_events import router as session_events_router


_OPTIONAL_ROUTERS = (
    ("consumer_signals", "src.app.routers.consumer_signals", "router"),
    ("decision_trace_events", "src.app.routers.decision_trace_events", "router"),
    ("hippograph", "src.app.routers.hippograph", "router"),
    ("decision_replay", "src.app.routers.decision_replay", "router"),
    ("market_ingestion_admin", "src.app.routers.market_ingestion_admin", "router"),
)


def register_intelligence_router_group(app: FastAPI) -> tuple[str, ...]:
    """Register the required session stream and optional intelligence surfaces."""
    registered = ["session_events"]
    app.include_router(session_events_router)
    log = logging.getLogger("shopsquire.startup")
    for name, module_name, attribute in _OPTIONAL_ROUTERS:
        try:
            module = importlib.import_module(module_name)
            app.include_router(getattr(module, attribute))
            registered.append(name)
        except Exception as exc:
            log.exception("failed to include %s router: %s", name, exc)
    app.state.intelligence_router_group = tuple(registered)
    return tuple(registered)


__all__ = ["register_intelligence_router_group"]
