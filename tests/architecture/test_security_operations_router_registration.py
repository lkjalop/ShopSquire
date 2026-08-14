from fastapi import FastAPI

from src.app.bootstrap.security_operations_router_group import (
    register_security_operations_router_group,
)


def test_security_operations_router_group_registers_all_available_surfaces() -> None:
    app = FastAPI()

    registered = register_security_operations_router_group(app)

    assert registered == (
        "email_security_admin", "email_security", "gmail_ingest", "m365_ingest",
        "admin_email_security", "admin_playbooks", "admin_storage",
        "admin_grafana_proxy", "admin_email", "outbound_email_quarantine",
    )
    assert app.state.security_operations_router_group == registered
    assert app.state.security_operations_router_failures == ()
    assert len(app.routes) > 4
