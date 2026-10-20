"""A slow local webhook transaction must not occupy the API event loop."""
import asyncio
import json
from threading import Event, get_ident
from time import perf_counter

from fastapi import FastAPI
import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_slow_webhook_keeps_health_responsive_and_preserves_database_owner(
    tmp_path, monkeypatch, record_testsuite_property,
):
    from src.app.models.database_ownership import database_owner
    from src.app.routers import payments
    from src.app.services import payment_webhook_delivery as delivery

    engine = create_engine('sqlite:///' + str(tmp_path / 'owned-webhook.sqlite3'))
    with Session(engine) as db:
        delivery.ensure_tables(db)
        db.commit()
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', '')
    monkeypatch.setattr(payments, '_is_non_dev_env', lambda *args: False)
    entered, release = Event(), Event()
    worker_threads = []
    original = payments._apply_payment_webhook_event

    def slow_apply(*args, **kwargs):
        worker_threads.append(get_ident())
        entered.set()
        if not release.wait(timeout=2):
            raise RuntimeError('Owned slow operation was not released')
        return original(*args, **kwargs)

    monkeypatch.setattr(payments, '_apply_payment_webhook_event', slow_apply)
    app = FastAPI()
    app.include_router(payments.router)

    @app.middleware('http')
    async def own_database(request, call_next):
        with database_owner(engine):
            return await call_next(request)

    @app.get('/health')
    async def health():
        return {'ok': True}

    async def exercise():
        loop_thread = get_ident()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1') as client:
            started = perf_counter()
            webhook = asyncio.create_task(client.post('/api/v1/payments/webhook',
                content=json.dumps({'id': 'evt_owned_loop', 'type': 'owned.noop', 'data': {'object': {}}}),
                headers={'content-type': 'application/json'}))
            try:
                assert await asyncio.to_thread(entered.wait, 1), 'Webhook work never started'
                response = await client.get('/health')
                elapsed = perf_counter() - started
                record_testsuite_property('webhook_health_elapsed_seconds', round(elapsed, 6))
                assert response.status_code == 200
                assert elapsed < 0.75, f'Health waited {elapsed:.3f}s behind webhook work'
                assert len(worker_threads) == 1
                assert worker_threads[0] != loop_thread
            finally:
                release.set()
                result = await asyncio.wait_for(webhook, timeout=3)
            assert result.status_code == 200, result.text

    try:
        asyncio.run(exercise())
        with Session(engine) as db:
            assert db.scalar(text("SELECT state FROM stripe_events WHERE event_id='evt_owned_loop'")) == 'processed'
    finally:
        release.set()
        engine.dispose()
