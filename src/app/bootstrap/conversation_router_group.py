"""Buyer conversation, escalation-adjacent support, and safe-link routes."""
from __future__ import annotations

import importlib
import logging

from fastapi import FastAPI

from src.app.bootstrap.router_registration import RequiredRouter, register_required_routers
from src.app.routers.chat import router as chat_router
from src.app.routers.chat_stream import router as chat_stream_router
from src.app.routers.safe_links import router as safe_links_router
from src.app.routers.support_complaints import router as support_complaints_router


CONVERSATION_ROUTER_GROUP = (
    RequiredRouter("support_complaints", support_complaints_router),
    RequiredRouter("chat", chat_router),
    RequiredRouter("chat_stream", chat_stream_router),
    RequiredRouter("safe_links", safe_links_router),
)

_OPTIONAL_ESCALATION_ROUTERS = (
    ("escalation_room", "src.app.routers.escalation_room", "router"),
    ("public_incidents", "src.app.routers.escalation_room", "public_router"),
)


def register_conversation_router_group(app: FastAPI) -> tuple[str, ...]:
    registered = list(register_required_routers(app, CONVERSATION_ROUTER_GROUP))
    failed: list[str] = []
    log = logging.getLogger("shopsquire.startup")
    for name, module_name, attribute in _OPTIONAL_ESCALATION_ROUTERS:
        try:
            module = importlib.import_module(module_name)
            app.include_router(getattr(module, attribute))
            registered.append(name)
        except Exception as exc:
            failed.append(name)
            log.exception("failed to include %s router: %s", name, exc)
    result = tuple(registered)
    app.state.conversation_router_group = result
    app.state.conversation_router_failures = tuple(failed)
    return result


__all__ = ["CONVERSATION_ROUTER_GROUP", "register_conversation_router_group"]
