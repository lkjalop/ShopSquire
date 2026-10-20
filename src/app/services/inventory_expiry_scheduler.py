"""Bounded maintenance of already-authorized reservation deadlines."""
from datetime import datetime, timezone
import logging
import os
from threading import Event, RLock, Thread
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from src.app.models.db import db_session
from src.app.services.inventory_transactions import expire_due

logger=logging.getLogger(__name__)
_WORKER_LOCK = RLock()


def run_once(*, session_factory=None, now=None, limit=100):
    if type(limit) is not int or not 1<=limit<=1000:
        raise ValueError('invalid_expiry_batch')
    clock=now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        raise ValueError('timezone_required')
    clock=clock.astimezone(timezone.utc)
    if session_factory is None:
        session_factory = db_session
    with session_factory() as db:
        rows=db.execute(text('''SELECT tenant_id FROM inventory_reservation
            WHERE status='reserved' AND expires_at<=:now
            ORDER BY expires_at,tenant_id,reservation_id LIMIT :limit'''),
            dict(now=clock.isoformat(),limit=limit)).all()
    tenants=list(dict.fromkeys(row[0] for row in rows))
    expired=0
    errors=[]
    for tenant in tenants:
        if expired>=limit:break
        try:
            with session_factory() as db:
                result=expire_due(db,tenant_id=tenant,now=clock,limit=limit-expired)
                db.commit()
                expired+=len(result)
        except Exception as exc:
            logger.exception('Reservation expiry batch failed for tenant %s',tenant)
            errors.append(dict(tenant_id=tenant,error=type(exc).__name__))
    return dict(expired=expired,errors=errors,status='partial_failure' if errors else 'completed',
                checked_at=clock.isoformat())


def start_inventory_expiry_scheduler(app):
    if os.getenv('INVENTORY_EXPIRY_SCHEDULER_ENABLED','0').lower() not in ('1','true','yes'):
        return
    with _WORKER_LOCK:
        existing=getattr(app.state,'inventory_expiry_thread',None)
        if existing is not None and existing.is_alive():return
        engine = getattr(app.state, 'engine', None)
        if engine is None:
            raise RuntimeError('Inventory expiry requires an application database owner')
        sessions = sessionmaker(bind=engine, expire_on_commit=False)
        interval=max(5,min(3600,float(os.getenv('INVENTORY_EXPIRY_INTERVAL_SECONDS','30'))))
        stop=Event()
        def loop():
            while not stop.is_set():
                try:
                    app.state.inventory_expiry_last_run=run_once(session_factory=sessions)
                except Exception as exc:
                    app.state.inventory_expiry_last_run=dict(status='failed',error=type(exc).__name__)
                    logger.exception('Reservation expiry scheduler failed')
                stop.wait(interval)
        thread=Thread(target=loop,name='inventory-expiry',daemon=True)
        app.state.inventory_expiry_stop=stop
        app.state.inventory_expiry_thread=thread
        thread.start()


def stop_inventory_expiry_scheduler(app):
    with _WORKER_LOCK:
        stop=getattr(app.state,'inventory_expiry_stop',None)
        if stop is not None:stop.set()
        thread=getattr(app.state,'inventory_expiry_thread',None)
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError('Inventory expiry worker did not stop')
