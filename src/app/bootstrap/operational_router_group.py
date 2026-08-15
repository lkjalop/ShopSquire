"""Required query, audit, health, and runtime-introspection surfaces."""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

from src.app.bootstrap.router_registration import RequiredRouter, register_required_routers
from src.app.routers.audit import router as audit_router
from src.app.routers.data_readiness import router as data_readiness_router
from src.app.routers.health import router as health_router
from src.app.routers.posthoc import router as posthoc_router
from src.app.routers.query import router as query_router
from src.app.routers.trace_debug import router as trace_debug_router
from src.app.versioning import get_api_version_info


version_router = APIRouter(tags=["meta"])


@version_router.get("/api/version", include_in_schema=True)
def api_version_info():
    return get_api_version_info()


OPERATIONAL_ROUTER_GROUP = (
    RequiredRouter("query", query_router),
    RequiredRouter("audit", audit_router),
    RequiredRouter("posthoc", posthoc_router),
    RequiredRouter("health", health_router),
    RequiredRouter("api_version", version_router),
    RequiredRouter("data_readiness", data_readiness_router),
    RequiredRouter("trace_debug", trace_debug_router),
)


def register_operational_router_group(app: FastAPI) -> tuple[str, ...]:
    registered = register_required_routers(app, OPERATIONAL_ROUTER_GROUP)
    app.state.operational_router_group = registered
    return registered


__all__ = ["register_operational_router_group"]
