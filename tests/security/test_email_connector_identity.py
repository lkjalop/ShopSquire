import json

import pytest

from src.app.services.email_connector_identity import (
    resolve_subscription,
    verify_m365_notification,
)


def test_subscription_registry_binds_provider_to_tenant(monkeypatch):
    monkeypatch.setenv(
        "EMAIL_CONNECTOR_SUBSCRIPTIONS_JSON",
        json.dumps(
            {
                "gmail": {
                    "projects/p/subscriptions/s1": {
                        "tenant_id": "tenant-a",
                        "audience": "https://shopsquire.example/ingest",
                    }
                }
            }
        ),
    )
    identity = resolve_subscription("gmail", "projects/p/subscriptions/s1")
    assert identity.tenant_id == "tenant-a"
    with pytest.raises(ValueError, match="unknown_connector_subscription"):
        resolve_subscription("gmail", "projects/p/subscriptions/other")


def test_m365_notification_requires_matching_client_state(monkeypatch):
    monkeypatch.setenv(
        "EMAIL_CONNECTOR_SUBSCRIPTIONS_JSON",
        json.dumps(
            {
                "m365": {
                    "sub-1": {
                        "tenant_id": "tenant-a",
                        "client_state": "expected-secret",
                    }
                }
            }
        ),
    )
    identity = resolve_subscription("m365", "sub-1")
    verify_m365_notification(identity, {"clientState": "expected-secret"})
    with pytest.raises(ValueError, match="m365_client_state_mismatch"):
        verify_m365_notification(identity, {"clientState": "wrong"})
