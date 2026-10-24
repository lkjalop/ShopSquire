"""Real worker threads retain each caller's context without sharing mutations."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Barrier
import pytest
from src.app.services import dependency_resilience as service

@pytest.fixture(autouse=True)
def owned_workers(monkeypatch):
    service.shutdown_resilience_executor(wait=True)
    monkeypatch.setattr(service, '_CIRCUITS', {})
    yield
    service.shutdown_resilience_executor(wait=True)

def test_worker_retains_request_context_and_preserves_the_caller():
    tenant = ContextVar('owned_tenant', default='unset')
    token = tenant.set('tenant-alpha')
    try:
        assert service.call_with_resilience('context.read', tenant.get, retries=0) == 'tenant-alpha'
        assert tenant.get() == 'tenant-alpha'
    finally:
        tenant.reset(token)

def test_each_completed_retry_gets_a_fresh_request_context():
    tenant = ContextVar('owned_retry_tenant', default='unset')
    token = tenant.set('tenant-alpha')
    seen = []
    def operation():
        seen.append(tenant.get())
        tenant.set('worker-mutation')
        if len(seen) == 1:
            raise RuntimeError('Completed transient failure')
        return seen[-1]
    try:
        assert service.call_with_resilience('context.retry', operation, retries=1, backoff_s=0) == 'tenant-alpha'
        assert seen == ['tenant-alpha', 'tenant-alpha']
        assert tenant.get() == 'tenant-alpha'
    finally:
        tenant.reset(token)

def test_concurrent_request_contexts_never_cross():
    tenant = ContextVar('owned_concurrent_tenant', default='unset')
    ready = Barrier(2)
    def caller(label):
        token = tenant.set(label)
        def operation():
            ready.wait(timeout=3)
            return tenant.get()
        try:
            return service.call_with_resilience('context.' + label, operation, retries=0, timeout_s=4)
        finally:
            tenant.reset(token)
    with ThreadPoolExecutor(max_workers=2) as callers:
        first = callers.submit(caller, 'tenant-alpha')
        second = callers.submit(caller, 'tenant-beta')
        assert first.result(timeout=5) == 'tenant-alpha'
        assert second.result(timeout=5) == 'tenant-beta'
    assert tenant.get() == 'unset'
