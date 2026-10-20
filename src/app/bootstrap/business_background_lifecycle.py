"""Registration boundary for optional commerce background services."""
from __future__ import annotations

import importlib
import inspect
import logging
import os
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI


def _register_pair(
    app: FastAPI, *, name: str, start: Callable[[], object], stop: Callable[[], object],
) -> None:
    started=False
    async def start_once():
        nonlocal started
        if started:return
        try:
            result=start()
            # A returned Task is an already-started worker, not a startup coroutine.
            if inspect.iscoroutine(result):await result
        except BaseException:
            # A start can allocate resources before raising. Preserve its error
            # while attempting cleanup; never silently declare readiness.
            try:
                result=stop()
                if inspect.isawaitable(result):await result
            except BaseException:
                started = True
                logging.getLogger(__name__).exception('Background cleanup failed: %s', name)
            raise
        started=True
    async def stop_once():
        nonlocal started
        if not started:return
        result=stop()
        if inspect.isawaitable(result):await result
        started=False
    app.router.add_event_handler("startup", start_once)
    app.router.add_event_handler("shutdown", stop_once)
    app.state.business_background_pairs.append((start_once,stop_once))
    current = list(getattr(app.state, "business_background_services", ()) or ())
    current.append(name)
    app.state.business_background_services = tuple(current)


def register_business_background_lifecycle(app: FastAPI) -> tuple[str, ...]:
    """Register optional services and retain explicit registration truth."""
    app.state.business_background_services = ()
    app.state.business_background_pairs = []
    failures: dict[str, str] = {}
    definitions = (
        ("security_observer", "src.app.security.observer_workers", "start_security_observer", "stop_security_observer"),
        ("retention", "src.app.services.retention", "start_retention_loop", "stop_retention_loop"),
        ("incident_sla", "src.app.services.incident_sla_scheduler", "start_incident_sla_scheduler", "stop_incident_sla_scheduler"),
        ("payment_reconcile", "src.app.services.payment_reconcile_scheduler", "start_payment_reconcile_scheduler", "stop_payment_reconcile_scheduler"),
    )
    for name, module_name, start_name, stop_name in definitions:
        try:
            module = importlib.import_module(module_name)
            start_fn = getattr(module, start_name)
            stop_fn = getattr(module, stop_name)
            _register_pair(
                app, name=name,
                start=lambda fn=start_fn: fn(app),
                stop=lambda fn=stop_fn: fn(app),
            )
        except Exception as exc:
            failures[name] = type(exc).__name__
    if str(os.getenv("WEBHOOK_DISPATCHER_WORKER_ENABLED", "1")).lower() in {
        "1", "true", "yes",
    }:
        try:
            module = importlib.import_module("src.app.services.webhook_dispatcher")
            _register_pair(
                app, name="webhook_dispatcher",
                start=lambda: module.start_worker(app),
                stop=module.stop_worker,
            )
        except Exception as exc:
            failures["webhook_dispatcher"] = type(exc).__name__
    app.state.business_background_lifecycle = {
        "registered": tuple(app.state.business_background_services),
        "optional_failures": failures,
    }
    return tuple(app.state.business_background_services)


async def start_business_background(app):
    """Explicit bridge for applications using a custom ASGI lifespan."""
    for start,_ in getattr(app.state,'business_background_pairs',[]):await start()


async def stop_business_background(app):
    failure = None
    for _,stop in reversed(getattr(app.state,'business_background_pairs',[])):
        try:
            await stop()
        except BaseException as exc:
            if failure is None:failure = exc
    if failure is not None:raise failure


@asynccontextmanager
async def managed_business_background(app,runtime_lifecycle):
    try:
        runtime_lifecycle.start(app)
        await start_business_background(app)
        yield
    finally:
        import sys
        primary_error = sys.exc_info()[1]
        cleanup_error = None
        try:
            await stop_business_background(app)
        except BaseException as exc:
            cleanup_error = exc
            logging.getLogger(__name__).exception('Business worker shutdown failed')
        finally:
            try:
                await runtime_lifecycle.stop()
            except BaseException as exc:
                if cleanup_error is None:
                    cleanup_error = exc
                logging.getLogger(__name__).exception('Runtime shutdown failed')
        if primary_error is None and cleanup_error is not None:
            raise cleanup_error


__all__ = ['register_business_background_lifecycle','start_business_background','stop_business_background']
