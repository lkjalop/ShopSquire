from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.app.erp.connector_runtime import (
    TenantTokenCache,
    compare_and_set_cursor,
    get_cursor_state,
    recover_stalled_inventory_runs,
    retry_after_seconds,
)
from src.app.models.db import db_session


def test_cursor_compare_and_set_rejects_stale_writer():
    tenant = "cas-tenant"
    provider = "cas-provider"
    initial = get_cursor_state(tenant_id=tenant, provider=provider)
    written = compare_and_set_cursor(
        tenant_id=tenant,
        provider=provider,
        expected_version=initial.version,
        cursor_value="page-2",
        checkpoint={"page": 1},
    )
    assert written.version == initial.version + 1
    assert written.checkpoint == {"page": 1}

    with pytest.raises(RuntimeError, match="connector_cursor_conflict"):
        compare_and_set_cursor(
            tenant_id=tenant,
            provider=provider,
            expected_version=initial.version,
            cursor_value="stale-page",
        )


def test_token_cache_is_tenant_and_subscription_scoped():
    cache = TenantTokenCache()
    cache.put(
        tenant_id="tenant-a",
        provider="erp",
        subscription_id="sub-a",
        token="token-a",
        expires_in_seconds=300,
    )
    assert cache.get(tenant_id="tenant-a", provider="erp", subscription_id="sub-a") == "token-a"
    assert cache.get(tenant_id="tenant-b", provider="erp", subscription_id="sub-a") is None
    assert cache.get(tenant_id="tenant-a", provider="erp", subscription_id="sub-b") is None


def test_retry_after_supports_seconds_and_http_date():
    assert retry_after_seconds("7") == 7
    now = datetime.now(timezone.utc)
    date_value = (now + timedelta(seconds=10)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    parsed = retry_after_seconds(date_value, now=now)
    assert parsed is not None
    assert 9 <= parsed <= 10


def test_stalled_inventory_run_is_reconciled():
    run_id = "stalled-runtime-test"
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO inventory_sync_runs
                (id, tenant_id, source, status, started_at, heartbeat_at,
                 records_seen, records_applied)
                VALUES
                (:id, 'tenant-a', 'test', 'started', :old, :old, 0, 0)
                """
            ),
            {"id": run_id, "old": "2020-01-01T00:00:00+00:00"},
        )
        db.commit()
    assert recover_stalled_inventory_runs(stale_after_seconds=30) >= 1
    with db_session() as db:
        row = db.execute(
            text("SELECT status, outcome_type FROM inventory_sync_runs WHERE id=:id"),
            {"id": run_id},
        ).fetchone()
    assert tuple(row) == ("stalled", "unavailable")


def test_stalled_recovery_is_registered_with_beat():
    from src.app.workers.celery_app import celery_app

    scheduled = celery_app.conf.beat_schedule["connector-stalled-job-recovery"]
    assert scheduled["task"].endswith("recover_stalled_connector_jobs")
