import pytest

from src.app.services import dependency_resilience as resilience


def test_timeout_cancels_queued_future(monkeypatch):
    class _Future:
        cancelled = False

        def result(self, timeout):
            raise resilience.FuturesTimeout()

        def cancel(self):
            self.cancelled = True
            return True

    future = _Future()
    executor = type("_Executor", (), {"submit": lambda self, _fn: future})()
    monkeypatch.setattr(resilience, "_executor", lambda: executor)
    monkeypatch.setitem(resilience._CIRCUITS, "test.cancel", resilience.CircuitState())

    with pytest.raises(TimeoutError):
        resilience.call_with_resilience("test.cancel", lambda: None, timeout_s=0.01, retries=0)
    assert future.cancelled is True
