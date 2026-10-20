"""Browser collection and its server must preserve the parent test runtime."""
import importlib.util
import os
import json
from pathlib import Path

import pytest
import requests

from src.app.models.db import get_engine


def load_browser_fixtures():
    path = Path(__file__).parents[1] / 'browser' / 'conftest.py'
    spec = importlib.util.spec_from_file_location('isolated_browser_fixture_probe', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_browser_fixture_collection_preserves_parent_environment_and_engine(monkeypatch):
    monkeypatch.setenv('E2E_BASE_URL', 'http://127.0.0.1:43123')
    monkeypatch.delenv('E2E_PORT', raising=False)
    before, engine = dict(os.environ), get_engine()
    load_browser_fixtures()
    assert dict(os.environ) == before
    assert get_engine() is engine


def test_browser_backend_owns_its_process_without_replacing_the_parent(pytestconfig, tmp_path_factory):
    module = load_browser_fixtures()
    before, engine = dict(os.environ), get_engine()
    lifecycle = module.browser_test_server.__wrapped__(pytestconfig, tmp_path_factory)
    runtime = next(lifecycle)
    try:
        assert runtime['owned'] is True
        assert runtime['database_url'] != os.environ['DATABASE_URL']
        assert dict(os.environ) == before
        assert get_engine() is engine
        assert requests.get(runtime['base_url'] + '/health', timeout=5).status_code == 200
        owner = json.loads((Path(runtime['database_path']).parent / 'owner.json').read_text(encoding='utf-8'))
        assert owner['pid'] == runtime['process_id']
    finally:
        try:
            next(lifecycle)
        except StopIteration:
            pass
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.get(runtime['base_url'] + '/health', timeout=2)
    assert dict(os.environ) == before
    assert get_engine() is engine
