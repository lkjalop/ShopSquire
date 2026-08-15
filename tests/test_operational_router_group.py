from fastapi import FastAPI

from src.app.bootstrap.operational_router_group import register_operational_router_group


def test_operational_router_group_registers_required_surfaces():
    app = FastAPI()

    registered = register_operational_router_group(app)
    paths = {route.path for route in app.routes}

    assert registered == (
        "query", "audit", "posthoc", "health", "api_version",
        "data_readiness", "trace_debug",
    )
    assert "/api/version" in paths
    assert any(path.endswith("/health") or path == "/health" for path in paths)
    assert app.state.operational_router_group == registered
