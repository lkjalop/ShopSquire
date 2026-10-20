import threading
from types import SimpleNamespace

import pytest

from src.app.security.observer_workers import (
    ObserverWorkGroup, observer_work_group, start_security_observer, stop_security_observer,
)


def test_shutdown_reports_a_running_job_and_keeps_it_owned_until_retry():
    group = ObserverWorkGroup()
    entered, release, exited = threading.Event(), threading.Event(), threading.Event()

    def job():
        entered.set()
        try:
            assert release.wait(3)
        finally:
            exited.set()

    assert group.submit(job)
    assert entered.wait(3)
    try:
        with pytest.raises(RuntimeError, match='shutdown budget'):
            group.stop(timeout=0.01)
        assert group.closed and not group.submit(lambda: None)
    finally:
        release.set()
        assert exited.wait(3)
        group.stop(timeout=1)
    assert not group._workers


def test_capacity_is_released_when_a_job_raises(monkeypatch):
    from src.app.security import observer_workers
    monkeypatch.setattr(observer_workers, '_PROCESS_CAPACITY', threading.BoundedSemaphore(1))
    group = ObserverWorkGroup()
    def failed():
        raise RuntimeError('test worker failure')
    assert group.submit(failed)
    group.stop(timeout=1)
    replacement = ObserverWorkGroup()
    assert replacement.submit(lambda: None)
    replacement.stop(timeout=1)


def test_one_apps_shutdown_does_not_close_another_apps_group():
    first, second = SimpleNamespace(state=SimpleNamespace()), SimpleNamespace(state=SimpleNamespace())
    a, b = observer_work_group(first), observer_work_group(second)
    assert a is not b
    stop_security_observer(first)
    assert not a.submit(lambda: None)
    assert b.submit(lambda: None)
    stop_security_observer(second)
    start_security_observer(first)
    replacement = observer_work_group(first)
    assert replacement is not a and replacement.submit(lambda: None)
    stop_security_observer(first)


def test_application_cannot_dispose_its_engine_while_an_observer_still_uses_it():
    import asyncio
    import src.app.main as main
    app = getattr(main, '_original_create_app', main.create_app)()
    disposed = []
    app.state.engine = SimpleNamespace(dispose=lambda: disposed.append(True))
    app.state.owns_engine = True
    entered, release = threading.Event(), threading.Event()
    group = observer_work_group(app)
    def job():
        entered.set()
        assert release.wait(3)
    assert group.submit(job) and entered.wait(3)
    shutdown = next(fn for fn in app.router.on_shutdown if fn.__name__ == '_on_shutdown')
    try:
        with pytest.raises(RuntimeError, match='still running'):
            asyncio.run(shutdown())
        assert disposed == []
    finally:
        release.set()
        group.stop(timeout=1)
    asyncio.run(shutdown())
    assert disposed == [True]


def test_startup_error_survives_cleanup_when_a_worker_still_owns_resources(monkeypatch):
    import asyncio
    import src.app.main as main
    app = getattr(main, '_original_create_app', main.create_app)()
    entered, release = threading.Event(), threading.Event()
    group = observer_work_group(app)
    def job():
        entered.set()
        assert release.wait(3)
    assert group.submit(job) and entered.wait(3)
    def failed_startup(*args, **kwargs):
        raise ValueError('required_startup_failure')
    monkeypatch.setattr(main, 'run_startup_step', failed_startup)
    async def lifetime():
        async with app.router.lifespan_context(app):
            pytest.fail('Required startup must not succeed')
    try:
        with pytest.raises(ValueError, match='required_startup_failure'):
            asyncio.run(lifetime())
    finally:
        release.set()
        group.stop(timeout=1)
