"""A model slot belongs to running transport work, including quarantined work."""
import threading
from types import SimpleNamespace

import pytest

from src.app.services import local_model_roles as roles
from src.app.services import model_execution_gateway as boundary
from tests.services.test_model_execution_gateway import _deployment, _request


@pytest.fixture
def owned_gate(monkeypatch):
    gate = roles._PriorityModelGate(1)
    monkeypatch.setattr(roles, '_model_gate', lambda *_args: gate)
    monkeypatch.setenv('OLLAMA_URL', 'http://127.0.0.1:1')
    return gate


def call(transport, *, timeout=1.0, **kwargs):
    return roles.execute_local_model_role(
        'owned input', role='recommendation_turn_router', purpose='transport-ownership',
        prompt_id='owned-transport', model='owned-transport-lab', digest='0' * 64,
        timeout_s=timeout, max_output_tokens=8, transport=transport, **kwargs,
    )


def assert_released(gate):
    with gate.condition:
        assert gate.condition.wait_for(lambda: gate.active == 0, timeout=1)


def test_timeout_keeps_model_owned_until_actual_transport_completion(owned_gate):
    release, entered, finished, overlap = (threading.Event() for _ in range(4))

    def slow(*_args):
        entered.set()
        try:
            assert release.wait(3)
            return 'quarantined output'
        finally:
            finished.set()

    try:
        with pytest.raises(RuntimeError, match='model_execution_timeout'):
            call(slow, timeout=0.15)
        assert entered.is_set() and not finished.is_set()
        assert owned_gate.active == 1
        with pytest.raises(RuntimeError, match='local_model_queue_timeout'):
            call(lambda *_args: overlap.set() or 'overlapping output', timeout=0.1)
        assert not overlap.is_set()
    finally:
        release.set()
        assert finished.wait(2)
    assert call(lambda *_args: 'recovered') == 'recovered'
    assert_released(owned_gate)


def test_invalid_request_releases_model_before_another_valid_request(owned_gate):
    with pytest.raises(ValueError):
        call(lambda *_args: 'must not run', tenant_id='')
    assert owned_gate.active == 0
    assert call(lambda *_args: 'valid successor') == 'valid successor'


def test_failed_gateway_construction_releases_model(monkeypatch, owned_gate):
    def fail(*_args, **_kwargs):
        raise RuntimeError('owned constructor failure')

    with monkeypatch.context() as scoped:
        scoped.setattr(roles, 'ModelExecutionGateway', fail)
        with pytest.raises(RuntimeError, match='owned constructor failure'):
            call(lambda *_args: 'must not run')
    assert owned_gate.active == 0
    assert call(lambda *_args: 'valid successor') == 'valid successor'


@pytest.mark.parametrize('outcome', ['completed', 'failed', 'blocked', 'cancelled', 'unenrolled', 'start_failed'])
def test_gateway_returns_undispatched_or_completed_lease_once(monkeypatch, outcome):
    released = []
    returned = threading.Event()
    deployment = _deployment()
    gateway = boundary.ModelExecutionGateway([deployment])
    request = _request(model_artifact_id='wrong') if outcome == 'blocked' else _request()
    called = []

    def transport(*_args):
        called.append(True)
        if outcome == 'failed':
            raise RuntimeError('owned transport failure')
        return 'owned result'

    if outcome == 'unenrolled':
        gateway = boundary.ModelExecutionGateway([])
    if outcome == 'start_failed':
        def fail_start(_self):
            raise RuntimeError('owned thread start failure')
        monkeypatch.setattr(boundary.threading.Thread, 'start', fail_start)
    def return_lease():
        released.append(True)
        returned.set()

    kwargs = dict(prompt='hello', transport=transport,
        cancellation_requested=lambda: outcome == 'cancelled',
        on_transport_finished=return_lease)
    if outcome in {'unenrolled', 'start_failed'}:
        with pytest.raises((ValueError, RuntimeError), match='model_deployment_not_enrolled|owned thread start failure'):
            gateway.execute(request, **kwargs)
    else:
        result = gateway.execute(request, **kwargs)
        assert result.status == outcome
    assert returned.wait(1)
    assert released == [True]
    assert bool(called) == (outcome in {'completed', 'failed'})


def test_schedule_identity_and_artifact_failure_replace_previous_execution(monkeypatch, owned_gate):
    seen = []
    assert call(lambda _prompt, _deployment, request: seen.append(request.run_id) or 'ok',
        execution_id='owned-previous') == 'ok'
    assert seen == ['owned-previous']
    monkeypatch.setattr(roles, 'verify_ollama_artifact', lambda **_kwargs: SimpleNamespace(status='mismatch'))
    with pytest.raises(RuntimeError, match='model_artifact_mismatch') as failure:
        roles.execute_local_model_role('owned input', role='recommendation_turn_router',
            purpose='transport-ownership', prompt_id='owned-transport',
            model='owned-transport-lab', digest='a' * 64, timeout_s=1,
            max_output_tokens=8, execution_id='owned-current')
    assert isinstance(failure.value, roles.LocalModelFailure)
    assert failure.value.failure_code == 'model_artifact_mismatch'
    metrics = roles.last_local_model_schedule_metrics()
    assert metrics['execution_id'] == 'owned-current'
    assert metrics['failure_code'] == 'model_artifact_mismatch'
    assert metrics['execution_ms'] == metrics['queue_ms'] == 0
    assert owned_gate.active == 0


def test_inflight_cancellation_returns_lease_only_after_quarantined_transport_finishes():
    release, entered, returned = (threading.Event() for _ in range(3))
    releases = []
    ledger = boundary.AgentRunEventLedger()
    gateway = boundary.ModelExecutionGateway([_deployment()], ledger=ledger)

    def transport(*_args):
        entered.set()
        assert release.wait(3)
        return 'quarantined cancellation output'

    def return_lease():
        releases.append(True)
        returned.set()

    try:
        result = gateway.execute(_request(timeout_ms=1000), prompt='hello', transport=transport,
            cancellation_requested=entered.is_set, on_transport_finished=return_lease)
        assert result.status == 'cancelled' and result.text is None
        assert entered.is_set() and not returned.is_set()
        assert result.late_result_quarantined
    finally:
        release.set()
    assert returned.wait(2)
    assert releases == [True]
    events = ledger.events_for(result.run_id, tenant_id='tenant-a')
    assert [event.event_type for event in events] == ['accepted', 'cancelled', 'late_result_quarantined']
    successor = gateway.execute(_request(), prompt='hello', transport=lambda *_args: 'recovered')
    assert successor.status == 'completed' and successor.text == 'recovered'
