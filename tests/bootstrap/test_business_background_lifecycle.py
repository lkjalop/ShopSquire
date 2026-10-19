from fastapi import FastAPI
import pytest

from src.app.bootstrap.business_background_lifecycle import (
    register_business_background_lifecycle,
)


def test_business_background_lifecycle_records_registration_truth(monkeypatch):
    monkeypatch.setenv("WEBHOOK_DISPATCHER_WORKER_ENABLED", "0")
    app = FastAPI()
    registered = register_business_background_lifecycle(app)
    projection = app.state.business_background_lifecycle
    assert tuple(projection["registered"]) == registered
    assert isinstance(projection["optional_failures"], dict)
    assert {"retention", "incident_sla", "payment_reconcile"}.issuperset(registered)


def test_custom_lifespan_runs_business_pairs_once_and_stops_in_reverse_order():
    import asyncio
    from src.app.bootstrap.business_background_lifecycle import _register_pair,start_business_background,stop_business_background
    app=FastAPI();app.state.business_background_pairs=[]
    calls=[]
    for name in ('first','second'):
        _register_pair(app,name=name,start=lambda n=name:calls.append('start:'+n),stop=lambda n=name:calls.append('stop:'+n))
    async def exercise():
        await start_business_background(app)
        await start_business_background(app)
        await stop_business_background(app)
        await stop_business_background(app)
    asyncio.run(exercise())
    assert calls==['start:first','start:second','stop:second','stop:first']


def test_starting_a_background_task_does_not_await_its_infinite_loop():
    import asyncio
    from src.app.bootstrap.business_background_lifecycle import _register_pair,start_business_background,stop_business_background
    app=FastAPI();app.state.business_background_pairs=[]
    tasks=[]
    def start():
        tasks.append(asyncio.create_task(asyncio.sleep(3600)))
        return tasks[-1]
    def stop():tasks[-1].cancel()
    _register_pair(app,name='long-running',start=start,stop=stop)
    async def exercise():
        await asyncio.wait_for(start_business_background(app),timeout=.1)
        await stop_business_background(app)
        await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(exercise())


def test_failed_start_cleans_partial_worker_and_preserves_original_error():
    import asyncio
    from src.app.bootstrap.business_background_lifecycle import _register_pair, start_business_background
    app = FastAPI(); app.state.business_background_pairs = []
    calls = []
    def start():
        calls.append('partial-start')
        raise RuntimeError('startup-failed')
    def stop():
        calls.append('cleanup')
        raise ValueError('cleanup-failed')
    _register_pair(app, name='partial', start=start, stop=stop)
    with pytest.raises(RuntimeError, match='startup-failed'):
        asyncio.run(start_business_background(app))
    assert calls == ['partial-start', 'cleanup']


def test_shutdown_attempts_every_worker_despite_one_failure():
    import asyncio
    from src.app.bootstrap.business_background_lifecycle import _register_pair, start_business_background, stop_business_background
    app = FastAPI(); app.state.business_background_pairs = []
    calls = []
    def bad_stop():
        calls.append('bad-stop')
        raise RuntimeError('stop-failed')
    _register_pair(app, name='first', start=lambda: None, stop=lambda: calls.append('first-stop'))
    _register_pair(app, name='last', start=lambda: None, stop=bad_stop)
    async def exercise():
        await start_business_background(app)
        with pytest.raises(RuntimeError, match='stop-failed'):
            await stop_business_background(app)
    asyncio.run(exercise())
    assert calls == ['bad-stop', 'first-stop']


def test_runtime_partial_start_failure_still_stops_runtime():
    import asyncio
    from src.app.bootstrap.business_background_lifecycle import managed_business_background
    calls = []
    class Runtime:
        def start(self, app):
            calls.append('partial-start')
            raise RuntimeError('runtime-start-failed')
        async def stop(self):
            calls.append('runtime-stop')
    async def exercise():
        with pytest.raises(RuntimeError, match='runtime-start-failed'):
            async with managed_business_background(FastAPI(), Runtime()):
                pass
    asyncio.run(exercise())
    assert calls == ['partial-start', 'runtime-stop']


def test_failed_stop_keeps_worker_owned_until_cleanup_succeeds():
    import asyncio
    from src.app.bootstrap.business_background_lifecycle import (
        _register_pair, start_business_background, stop_business_background,
    )
    app = FastAPI()
    app.state.business_background_pairs = []
    calls = []

    def stop():
        calls.append('stop')
        if calls.count('stop') == 1:
            raise RuntimeError('worker_still_running')

    _register_pair(app, name='retry', start=lambda: calls.append('start'), stop=stop)

    async def exercise():
        await start_business_background(app)
        with pytest.raises(RuntimeError, match='worker_still_running'):
            await stop_business_background(app)
        await start_business_background(app)
        await stop_business_background(app)

    asyncio.run(exercise())
    assert calls == ['start', 'stop', 'stop']


def test_cleanup_failures_do_not_replace_the_startup_error():
    import asyncio
    from src.app.bootstrap.business_background_lifecycle import managed_business_background
    calls = []

    class Runtime:
        def start(self, app):
            raise RuntimeError('required_start_failed')

        async def stop(self):
            calls.append('runtime-stop')
            raise ValueError('cleanup_failed')

    async def exercise():
        with pytest.raises(RuntimeError, match='required_start_failed'):
            async with managed_business_background(FastAPI(), Runtime()):
                pass

    asyncio.run(exercise())
    assert calls == ['runtime-stop']
