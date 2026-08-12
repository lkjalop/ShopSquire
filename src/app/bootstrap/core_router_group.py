"""Core runtime router group kept separate from application lifecycle composition."""

from __future__ import annotations

from fastapi import FastAPI

from src.app.bootstrap.router_registration import RequiredRouter, register_required_routers
from src.app.observability.metrics import router as metrics_router
from src.app.routers.decisions import router as decisions_router
from src.app.routers.image_sidecar import router as image_sidecar_router
from src.app.routers.incident import router as incident_router
from src.app.routers.session_memory import router as session_memory_router
from src.app.routers.sla import router as sla_router
from src.app.routers.vision import router as vision_router
from src.app.routers.voice import router as voice_router


CORE_ROUTER_GROUP = (
    RequiredRouter("incident", incident_router),
    RequiredRouter("metrics", metrics_router),
    RequiredRouter("sla", sla_router),
    RequiredRouter("session_memory", session_memory_router),
    RequiredRouter("decisions", decisions_router),
    RequiredRouter("voice", voice_router),
    RequiredRouter("vision", vision_router),
    RequiredRouter("image_sidecar", image_sidecar_router),
)


def register_core_router_group(app: FastAPI) -> tuple[str, ...]:
    return register_required_routers(app, CORE_ROUTER_GROUP)
