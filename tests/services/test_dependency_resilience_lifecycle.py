from src.app.services import dependency_resilience as resilience


def test_resilience_executor_can_shutdown_and_restart():
    resilience.shutdown_resilience_executor(wait=True)
    assert resilience.call_with_resilience(
        "lifecycle-test",
        lambda: "first",
        retries=0,
    ) == "first"
    first = resilience._EXECUTOR
    assert first is not None
    resilience.shutdown_resilience_executor(wait=True)
    assert resilience._EXECUTOR is None
    assert resilience.call_with_resilience(
        "lifecycle-test",
        lambda: "second",
        retries=0,
    ) == "second"
    assert resilience._EXECUTOR is not None
    assert resilience._EXECUTOR is not first
    resilience.shutdown_resilience_executor(wait=True)
