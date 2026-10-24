"""A timeout cannot authorize an overlapping automatic dependency attempt."""
from threading import Event, Lock
import pytest
from src.app.services import dependency_resilience as service

@pytest.fixture(autouse=True)
def own_workers(monkeypatch):
    service.shutdown_resilience_executor(wait=True)
    monkeypatch.setattr(service, '_CIRCUITS', {})
    yield
    service.shutdown_resilience_executor(wait=True)

def test_running_timeout_never_starts_an_overlapping_attempt():
    entered, release = Event(), Event()
    guard = Lock()
    calls = []
    def operation():
        with guard:
            calls.append('entered')
        entered.set()
        if not release.wait(3):
            raise RuntimeError('Owned worker was not released')
        return 'finished'
    try:
        with pytest.raises(TimeoutError):
            service.call_with_resilience('owned.running', operation, timeout_s=0.03, retries=2, backoff_s=0)
        assert entered.wait(0.5)
        assert len(calls) == 1, 'Caller timeout must not duplicate the still-running operation'
    finally:
        release.set()

def test_operation_timeout_is_terminal_until_explicit_reconciliation():
    calls = []
    def uncertain_operation():
        calls.append('attempt')
        raise TimeoutError('Provider acceptance is unknown')
    with pytest.raises(TimeoutError):
        service.call_with_resilience('owned.uncertain', uncertain_operation, retries=2, backoff_s=0)
    assert calls == ['attempt'], 'A transport timeout cannot prove that an effect did not happen'

def test_completed_non_timeout_failure_retains_the_existing_retry():
    calls = []
    def operation():
        calls.append('attempt')
        if len(calls) == 1:
            raise RuntimeError('Completed transient read failure')
        return 'useful result'
    assert service.call_with_resilience('owned.completed', operation, retries=1, backoff_s=0) == 'useful result'
    assert calls == ['attempt', 'attempt']

def test_terminal_timeout_still_updates_the_circuit_breaker():
    def timeout():
        raise TimeoutError('owned timeout')
    with pytest.raises(TimeoutError):
        service.call_with_resilience('owned.breaker', timeout, breaker_failures=1, retries=2, backoff_s=0)
    with pytest.raises(RuntimeError, match='circuit_open:owned.breaker'):
        service.call_with_resilience('owned.breaker', lambda: 'must not run', retries=0)
