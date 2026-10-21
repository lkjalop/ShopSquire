from contextlib import contextmanager
from uuid import uuid4

import pytest

from src.app.services import outbound_email_monitor as monitor


def test_anomalies_and_analysis_never_mix_tenants_with_the_same_agent():
    agent = 'scope-' + uuid4().hex
    for tenant in ('scope-a', 'scope-b'):
        event = monitor.record_outbound_email_event(
            tenant_id=tenant, agent_id=agent, to='fixture@example.invalid',
            subject='plain', body='fixture', now_ts=1000)
        monitor.store_outbound_anomaly(tenant_id=tenant, agent_id=agent,
            event_id=event['id'], analysis={'anomalous': True, 'score': 1,
            'reasons': [tenant + '-PRIVATE_CANARY']}, now_ts=1000)
    items = monitor.list_outbound_anomalies(tenant_id='scope-a')
    assert items and all(item['tenant_id'] == 'scope-a' for item in items)
    assert 'scope-b-PRIVATE_CANARY' not in str(items)
    analysis = monitor.analyze_agent_outbound_email(
        tenant_id='scope-a', agent_id=agent, now_ts=1001)
    assert analysis['events'] == 1


def test_anomaly_storage_failure_is_explicit_instead_of_an_empty_healthy_list(monkeypatch):
    @contextmanager
    def unavailable():
        raise ConnectionError('database offline')
        yield
    monkeypatch.setattr(monitor, 'db_session', unavailable)
    with pytest.raises(RuntimeError, match='outbound_monitor_unavailable'):
        monitor.list_outbound_anomalies(tenant_id='scope-a')
