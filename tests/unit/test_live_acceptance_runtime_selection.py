import importlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('module_name', [
    'tests.acceptance.test_golden_workload_matrix',
    'tests.acceptance.test_swap_rate_battery',
])
def test_live_acceptance_does_not_probe_ambient_server(monkeypatch, module_name):
    monkeypatch.delenv('SHOPSQUIRE_ACCEPTANCE_BASE_URL', raising=False)
    monkeypatch.delenv('SHOPSQUIRE_ACCEPTANCE_LIVE', raising=False)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200)
    monkeypatch.setattr('httpx.get', get)
    module = importlib.reload(importlib.import_module(module_name))
    assert calls == [], 'Collection must not contact a user-owned backend'
    assert module.live.args[0] is True


def test_explicit_acceptance_runtime_is_used(monkeypatch):
    from tests.acceptance.live_runtime import live_base_url
    monkeypatch.setenv('SHOPSQUIRE_ACCEPTANCE_LIVE', '1')
    monkeypatch.setenv('SHOPSQUIRE_ACCEPTANCE_BASE_URL', 'http://127.0.0.1:8102/')
    assert live_base_url() == 'http://127.0.0.1:8102'


@pytest.mark.parametrize('url', ['', 'http://supplier.example',
    'http://user:password@127.0.0.1:8102', 'http://127.0.0.1:8102?key=value'])
def test_live_acceptance_rejects_unscoped_runtime(monkeypatch, url):
    from tests.acceptance.live_runtime import live_base_url
    monkeypatch.setenv('SHOPSQUIRE_ACCEPTANCE_LIVE', '1')
    monkeypatch.setenv('SHOPSQUIRE_ACCEPTANCE_BASE_URL', url)
    with pytest.raises(ValueError):
        live_base_url()
