import asyncio
from types import SimpleNamespace

from fastapi import FastAPI

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
    monkeypatch.setattr(
        lifecycle.importlib, "import_module",
        lambda _name: SimpleNamespace(start=start, stop=stop),
    )
    app = FastAPI()

    assert lifecycle.register_security_background_lifecycle(app) == ("one",)
    asyncio.run(app.router.startup())
    asyncio.run(app.router.shutdown())

    assert calls == [("start", app)]
    assert app.state.security_background_import_failures == ()
    assert app.state.security_background_runtime_failures == ({
        "service": "one", "phase": "stop", "error_type": "RuntimeError",
    },)
