from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.bootstrap import security_background_lifecycle as lifecycle


def test_background_lifecycle_records_registration_and_runtime_failure(monkeypatch):
    calls = []

    def start(app):
        calls.append(("start", app))

    def stop(_app):
        raise RuntimeError("stop_failed")

    monkeypatch.setattr(lifecycle, "SECURITY_BACKGROUND_SERVICES", (
        lifecycle.BackgroundServiceRegistration("one", "fake.module", "start", "stop"),
    ))
    original_import = lifecycle.importlib.import_module
    monkeypatch.setattr(
        lifecycle.importlib, "import_module",
        lambda name, *a, **kw: (SimpleNamespace(start=start, stop=stop)
                              if name == "fake.module" else original_import(name, *a, **kw)),
    )
    app = FastAPI()

    assert lifecycle.register_security_background_lifecycle(app) == ("one",)
    with TestClient(app):
        pass

    assert calls == [("start", app)]
    assert app.state.security_background_import_failures == ()
    assert app.state.security_background_runtime_failures == ({
        "service": "one", "phase": "stop", "error_type": "RuntimeError",
    },)
