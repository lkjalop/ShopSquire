"""Test-runner metadata must not alter pricing work or verifier configuration."""
import os
from types import SimpleNamespace

import pytest

from src.app.routers import pricing


@pytest.fixture
def pricing_runtime(monkeypatch):
    monkeypatch.setenv('DECISION_VERIFIER_STRICT', '1')
    flags = {
        'AGENT_ROLLOUT_PERCENT': 100, 'KILL_SWITCH': False,
        'CAPABILITIES': {'pricing': {'enabled': True, 'rollout_percent': 100}},
        'CHAOS': {'enabled': False}, 'DEGRADATION': {'enabled': False},
        'DECISION_LOG_WRITES_ENABLED': True,
    }
    calls = []
    persisted = []
    result = SimpleNamespace(proposal={'discount_cents': 200},
        firewall={'allowed': True, 'approval_required': False}, executed=False, timings=None)

    class Orchestrator:
        def __init__(self, *args):
            pass

        def run(self, uid, payload, **options):
            calls.append((uid, payload, options))
            return result

    monkeypatch.setattr(pricing, 'Orchestrator', Orchestrator)
    monkeypatch.setattr(pricing, '_ff_get_flags', lambda: flags)
    monkeypatch.setattr(pricing, 'get_settings', lambda: SimpleNamespace(app_env='production'))
    monkeypatch.setattr(pricing, 'TokenBudget', lambda _: SimpleNamespace(
        check_budget=lambda *args: (True, 'ok', {}), record_usage=lambda *args: None))
    monkeypatch.setattr(pricing, 'Memory', lambda _: SimpleNamespace(
        get_context=lambda uid: {'kv': {}}, set_kv=lambda *args: None))
    monkeypatch.setattr(pricing, 'analyze_payload', lambda _: {'severity': 'info', 'details': {}})
    monkeypatch.setattr(pricing, 'cb_record', lambda *args: None)

    def persist(**kwargs):
        persisted.append((os.getenv('DECISION_VERIFIER_STRICT'), kwargs))

    monkeypatch.setattr('src.app.services.persistence.persist_decision_and_audits', persist)
    return calls, persisted, result


@pytest.mark.parametrize('marker', [
    'tests/test_chaos.py::test_no_chaos_latency_when_disabled (call)',
    'owned_pricing_control (call)',
])
def test_pricing_executes_the_same_proposal_path_independent_of_test_name(monkeypatch, pricing_runtime, marker):
    monkeypatch.setenv('PYTEST_CURRENT_TEST', marker)
    calls, persisted, expected = pricing_runtime
    response = pricing.suggest(uid='owned-pricing-lab', cart_total_cents=12000, redis=None, role='merchant')
    assert isinstance(response, dict)
    assert response['proposal'] == expected.proposal
    assert response['firewall'] == expected.firewall
    assert response['executed'] is False
    assert len(calls) == len(persisted) == 1
    assert calls[0][1]['cart_total_cents'] == 12000


@pytest.mark.parametrize('configured', ['1', '0', None])
def test_pricing_preserves_verifier_configuration_before_during_and_after_persistence(monkeypatch, pricing_runtime, configured):
    if configured is None:
        monkeypatch.delenv('DECISION_VERIFIER_STRICT', raising=False)
    else:
        monkeypatch.setenv('DECISION_VERIFIER_STRICT', configured)
    calls, persisted, expected = pricing_runtime
    response = pricing.suggest(uid='owned-pricing-lab', cart_total_cents=12000, redis=None, role='merchant')
    assert response['proposal'] == expected.proposal
    assert len(calls) == len(persisted) == 1
    assert persisted[0][0] == configured
    assert os.getenv('DECISION_VERIFIER_STRICT') == configured
