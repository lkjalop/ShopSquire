import pytest
from fastapi import FastAPI

from src.app.bootstrap.startup_readiness import run_startup_step


def test_optional_startup_failure_is_typed_and_does_not_abort():
    app = FastAPI()

    result = run_startup_step(
        app, name="optional_demo", criticality="optional",
        operation=lambda: (_ for _ in ()).throw(ConnectionError("down")),
    )

    assert result is None
    assert app.state.startup_capabilities["optional_demo"]["status"] == "degraded"
    assert app.state.startup_capabilities["optional_demo"]["error_type"] == "ConnectionError"


def test_required_startup_failure_is_recorded_and_raised():
    app = FastAPI()
    with pytest.raises(RuntimeError, match="broken"):
        run_startup_step(
            app, name="migrations", criticality="required",
            operation=lambda: (_ for _ in ()).throw(RuntimeError("broken")),
        )
    assert app.state.startup_capabilities["migrations"]["status"] == "failed"
