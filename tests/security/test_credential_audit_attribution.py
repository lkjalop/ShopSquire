"""Authentication emits useful attribution without retaining the credential."""
import json

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.app.security import auth, insider_threat_detector
from src.app.observability import iam_events


@pytest.mark.parametrize("factory", ["require_role", "require_role_or_oidc"])
@pytest.mark.parametrize("decision", ["granted", "role_denied", "ip_denied"])
def test_auth_audit_and_insider_signals_do_not_contain_the_api_key(monkeypatch, factory, decision):
    key = "synthetic-owner-credential-must-never-enter-audit-records"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("OWNER_API_KEY", key)
    monkeypatch.setenv("ADMIN_IP_ALLOWLIST", "192.0.2.1" if decision == "ip_denied" else "")
    # Membership/ABAC have their own boundary tests; this fixture observes the
    # audit transports while preserving each factory's credential/role checks.
    monkeypatch.setattr(auth, "_abac_enabled", lambda: False)
    monkeypatch.setattr(auth, "_authorize_operator_tenant", lambda **kwargs: None)
    monkeypatch.setattr(insider_threat_detector, "_is_within_business_hours", lambda hour: False)
    events, signals = [], []
    monkeypatch.setattr(iam_events, "emit_iam_activity", lambda **kwargs: events.append(kwargs))
    monkeypatch.setattr(insider_threat_detector, "_emit", lambda signal: signals.append(signal.to_dict()))
    allowed = [auth.ROLE_MERCHANT] if decision == "role_denied" else [auth.ROLE_OWNER]
    dependency = getattr(auth, factory)(allowed)
    app = FastAPI()

    @app.get("/protected")
    def protected(role=Depends(dependency)):
        return {"role": role}

    response = TestClient(app, client=("198.51.100.240", 50000)).get(
        "/protected", headers={"x-api-key": key})
    assert response.status_code == (200 if decision == "granted" else 403), response.text
    assert events
    if decision != "role_denied":
        assert signals  # Do not satisfy confidentiality by disabling detection.
    records = json.dumps({"events": events, "signals": signals})
    assert key not in records
    actors = [event["subject"]["actor_id"] for event in events] + [signal["actor"] for signal in signals]
    assert len(set(actors)) == 1
    assert actors[0].startswith("credential:")
