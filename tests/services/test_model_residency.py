from src.app.services import model_residency


def test_router_restore_is_debounced(monkeypatch):
    created = []

    class _Timer:
        def __init__(self, delay, fn):
            self.delay = delay
            self.fn = fn
            self.cancelled = False
            self.name = ""
            self.daemon = False
            created.append(self)

        def is_alive(self):
            return not self.cancelled

        def cancel(self):
            self.cancelled = True

        def start(self):
            return None

    monkeypatch.setattr(model_residency.threading, "Timer", _Timer)
    monkeypatch.setattr(model_residency, "_TIMER", None)

    assert model_residency.schedule_router_restore() is True
    assert model_residency.schedule_router_restore() is True
    assert len(created) == 2
    assert created[0].cancelled is True
    assert created[1].cancelled is False
    assert model_residency.router_restore_status()["status"] == "scheduled"


def test_router_restore_can_be_disabled(monkeypatch):
    monkeypatch.setenv("CV_RESTORE_TEXT_ROUTER_AFTER_IMAGE", "0")
    assert model_residency.schedule_router_restore() is False
