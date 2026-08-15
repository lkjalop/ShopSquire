"""Buyer conversation, escalation-adjacent support, and safe-link routes."""
from __future__ import annotations

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


def register_conversation_router_group(app: FastAPI) -> tuple[str, ...]:
    registered = register_required_routers(app, CONVERSATION_ROUTER_GROUP)
    app.state.conversation_router_group = registered
    return registered


__all__ = ["CONVERSATION_ROUTER_GROUP", "register_conversation_router_group"]
