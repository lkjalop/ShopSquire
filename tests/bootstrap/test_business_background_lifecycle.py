from fastapi import FastAPI

from src.app.bootstrap.business_background_lifecycle import (
    register_business_background_lifecycle,
)


def test_business_background_lifecycle_records_registration_truth(monkeypatch):
    monkeypatch.setenv("WEBHOOK_DISPATCHER_WORKER_ENABLED", "0")
    app = FastAPI()
    registered = register_business_background_lifecycle(app)
    projection = app.state.business_background_lifecycle
    assert tuple(projection["registered"]) == registered
    assert isinstance(projection["optional_failures"], dict)
    assert {"retention", "incident_sla", "payment_reconcile"}.issuperset(registered)
