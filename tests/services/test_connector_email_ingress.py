from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.app.services.connector_email_ingress import identity_for_worker_item


def test_strict_worker_identity_comes_from_subscription(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv(
        "EMAIL_CONNECTOR_SUBSCRIPTIONS_JSON",
        json.dumps(
            {
                "gmail": {
                    "gmail-sub-a": {
                        "tenant_id": "tenant-a",
                        "audience": "push-a",
                    }
                },
                "m365": {
                    "m365-sub-b": {
                        "tenant_id": "tenant-b",
                        "client_state": "state-b",
                    }
                },
            }
        ),
    )

    gmail = identity_for_worker_item(
        "gmail",
        {"subscription_id": "gmail-sub-a", "tenant_id": "tenant-a"},
    )
    m365 = identity_for_worker_item(
        "m365",
        {"subscription_id": "m365-sub-b"},
    )
    assert gmail.tenant_id == "tenant-a"
    assert m365.tenant_id == "tenant-b"

    with pytest.raises(ValueError, match="tenant_subscription_mismatch"):
        identity_for_worker_item(
            "gmail",
            {"subscription_id": "gmail-sub-a", "tenant_id": "tenant-b"},
        )
    with pytest.raises(ValueError, match="unknown_connector_subscription"):
        identity_for_worker_item(
            "m365",
            {"subscription_id": "not-registered", "tenant_id": "tenant-b"},
        )


def test_polling_workers_cannot_bypass_durable_ingress():
    root = Path(__file__).resolve().parents[2]
    worker = (root / "src/app/workers/email_connector_worker.py").read_text(
        encoding="utf-8"
    )
    scheduled = (root / "src/app/tasks/email_poll_tasks.py").read_text(
        encoding="utf-8"
    )
    for source in (worker, scheduled):
        assert "persist_connector_email" in source
        assert "from src.app.security.email_security import evaluate_email_security" not in source
        assert "evaluate_email_security(" not in source
