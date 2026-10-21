"""Tier cache must follow the request memory owner unless explicitly overridden."""
import json
from types import SimpleNamespace

import pytest

from src.app.security.firewall import TransactionFirewall
from src.app.services.orchestrator import Orchestrator


class CacheClient:
    def __init__(self, label):
        self.label = label
        self.reads = []
        self.closed = False

    def get(self, key):
        assert not self.closed
        self.reads.append(key)
        return json.dumps({'owner': self.label})

    def close(self):
        self.closed = True


@pytest.fixture
def factory(monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://ambient-cache.invalid:6379/0')
    calls = []
    client = CacheClient('explicit-cache')

    def create(**kwargs):
        calls.append(kwargs)
        return client

    monkeypatch.setattr('src.app.services.redis_factory.create_redis_client', create)
    return calls, client


@pytest.mark.parametrize('owner', ['request-a', 'request-b'])
def test_tier_cache_borrows_the_exact_request_client_without_opening_an_ambient_backend(factory, owner):
    calls, unused = factory
    borrowed = CacheClient(owner)
    orch = Orchestrator(SimpleNamespace(redis=borrowed), TransactionFirewall({}), {})
    assert orch.tier_router.cache._redis is borrowed
    assert calls == []
    assert orch.tier_router.cache.get('owned-key') == {'owner': owner}
    assert borrowed.reads == ['owned-key']
    assert unused.reads == []
    assert borrowed.closed is False


def test_local_memory_does_not_reopen_the_unavailable_ambient_redis_backend(factory):
    calls, unused = factory
    orch = Orchestrator(SimpleNamespace(redis=None), TransactionFirewall({}), {})
    cache = orch.tier_router.cache
    assert cache.is_shared_backend is False
    cache.set('local-key', {'owner': 'local-only'})
    assert cache.get('local-key') == {'owner': 'local-only'}
    assert calls == unused.reads == []


def test_an_explicit_operator_cache_url_retains_its_existing_override(factory):
    calls, explicit = factory
    borrowed = CacheClient('request')
    flags = {'REDIS_URL': 'redis://explicit-cache.example.test:6379/0'}
    orch = Orchestrator(SimpleNamespace(redis=borrowed), TransactionFirewall(flags), flags)
    assert orch.tier_router.cache._redis is explicit
    assert [row['url'] for row in calls] == [flags['REDIS_URL']]
    assert orch.tier_router.cache.get('configured-key') == {'owner': 'explicit-cache'}
    assert borrowed.reads == []
    assert borrowed.closed is False
