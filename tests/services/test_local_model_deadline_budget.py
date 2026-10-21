"""Queue and verification must not inflate the caller's remaining model budget."""
from types import SimpleNamespace

import pytest

from src.app.services import local_model_roles as roles


@pytest.fixture
def clock_gate(monkeypatch):
    state = SimpleNamespace(now=0.0, consumed=0.0, releases=0, acquired=0, timeouts=[])

    class Gate:
        def acquire(self, *, priority, timeout):
            state.acquired += 1
            state.now += state.consumed
            return True, state.consumed * 1000

        def release(self):
            state.releases += 1

    monkeypatch.setenv('OLLAMA_URL', 'http://127.0.0.1:1')
    monkeypatch.setattr(roles, 'time', SimpleNamespace(perf_counter=lambda: state.now))
    monkeypatch.setattr(roles, '_model_gate', lambda *args: Gate())
    return state


def execute(state, *, timeout=5.0, digest='0' * 64):
    def transport(prompt, deployment, request):
        state.timeouts.append(request.timeout_ms)
        return 'owned deadline response'

    return roles.execute_local_model_role('owned input', role='supplier_document_polisher',
        purpose='deadline-control', prompt_id='deadline-control', model='owned-clock-lab',
        digest=digest, timeout_s=timeout, max_output_tokens=20, transport=transport)


@pytest.mark.parametrize('consumed,expected_ms', [
    (0.1004, 4899), (4.93925, 60), (4.87925, 120), (0.0, 5000),
])
def test_dispatch_budget_rounds_down_after_queue_work(clock_gate, consumed, expected_ms):
    clock_gate.consumed = consumed
    assert execute(clock_gate) == 'owned deadline response'
    assert clock_gate.timeouts == [expected_ms]
    assert clock_gate.timeouts[0] <= (5.0 - consumed) * 1000
    assert clock_gate.releases == 1


@pytest.mark.parametrize('consumed', [4.951, 5.01])
def test_less_than_the_minimum_transport_budget_does_not_dispatch(clock_gate, consumed):
    clock_gate.consumed = consumed
    with pytest.raises(RuntimeError, match='local_model_deadline_exhausted'):
        execute(clock_gate)
    assert clock_gate.acquired == clock_gate.releases == 1
    assert clock_gate.timeouts == []
    metrics = roles.last_local_model_schedule_metrics()
    assert metrics['status'] == 'timed_out'
    assert metrics['failure_code'] == 'local_model_deadline_exhausted'


@pytest.mark.parametrize('budget,expected_verification', [(0.075, 0.075), (0.1, 0.1), (5.0, 2.0)])
def test_artifact_verification_respects_the_normalized_role_budget(monkeypatch, clock_gate, budget, expected_verification):
    seen = []

    def verify(**kwargs):
        seen.append(kwargs['timeout_s'])
        return SimpleNamespace(status='unavailable')

    monkeypatch.setattr(roles, 'verify_ollama_artifact', verify)
    with pytest.raises(RuntimeError, match='model_artifact_unavailable'):
        execute(clock_gate, timeout=budget, digest='1' * 64)
    assert seen == [expected_verification]
    assert seen[0] <= budget
    assert clock_gate.acquired == clock_gate.releases == 0
    assert clock_gate.timeouts == []
