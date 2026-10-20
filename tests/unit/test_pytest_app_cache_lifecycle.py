"""Test-scoped app caching must not retain engines or alter session ownership."""
from types import SimpleNamespace
import gc
import weakref
import pytest


@pytest.mark.parametrize('owns_engine', [True, False])
def test_temporary_app_is_released_without_closing_borrowed_engine(monkeypatch, owns_engine):
    from tests import conftest as harness
    from src.app.models.db import get_engine
    original = get_engine()
    closed = []
    temporary_engine = SimpleNamespace(dispose=lambda: closed.append(True))
    baseline = SimpleNamespace(state=SimpleNamespace(engine=original, owns_engine=False))
    temporary = SimpleNamespace(state=SimpleNamespace(engine=temporary_engine,
                                                       owns_engine=owns_engine))
    apps = {'session': baseline}
    monkeypatch.setattr(harness, '_SINGLETONS', apps)
    lifecycle = harness._restore_db_engine.__wrapped__()
    next(lifecycle)
    apps['temporary-test-url'] = temporary
    with pytest.raises(StopIteration):
        next(lifecycle)
    assert apps == {'session': baseline}, 'temporary apps must not accumulate across tests'
    assert baseline.state.engine is original
    assert closed == ([True] if owns_engine else [])


def test_teardown_releases_unreachable_app_cycles_and_preserves_a_live_owner(monkeypatch, tmp_path):
    from tests import conftest as harness
    from src.app.models.db import get_engine
    class App:
        pass
    apps = {}
    monkeypatch.setattr(harness, '_SINGLETONS', apps)
    monkeypatch.setenv('PYTEST_DIAGNOSTIC_GC_INTERVAL', '0')
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        with (tmp_path / 'live-owner').open('w') as borrowed:
            lifecycle = harness._restore_db_engine.__wrapped__()
            next(lifecycle)
            temporary = App()
            temporary.self = temporary
            temporary.state = SimpleNamespace(engine=get_engine(), owns_engine=False)
            temporary.handle = (tmp_path / 'unreachable-owner').open('w')
            app_ref, handle_ref = weakref.ref(temporary), weakref.ref(temporary.handle)
            apps['temporary'] = temporary
            del temporary
            with pytest.raises(StopIteration):
                next(lifecycle)
            assert apps == {}
            assert app_ref() is None and handle_ref() is None
            assert borrowed.closed is False
    finally:
        gc.collect()
        if was_enabled:
            gc.enable()
