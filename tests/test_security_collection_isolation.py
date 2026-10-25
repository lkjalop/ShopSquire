"""Collecting security tests must not replace the shared runtime configuration."""
import os
import runpy
from pathlib import Path

import pytest

import src.app.models.db as dbmod


@pytest.mark.parametrize("filename", [
    "test_security_indirect_prompt_injection.py",
    "test_security_prompt_injection_endpoints.py",
    "test_admin_overview.py",
    "test_orders_status.py",
    "test_order_history_paging.py",
    "test_security_event_tags.py",
    "test_security_observer_paths.py",
])
def test_security_module_import_preserves_runtime(filename, monkeypatch):
    keys = ("DATABASE_URL", "DATABASE_URL_RO", "FEATURE_FLAGS_PATH", "SECURITY_BLOCK_MODE", "SKIP_OBSERVER_ENDPOINTS")
    before = {key: os.environ.get(key) for key in keys}
    engine, factory = dbmod.engine, dbmod.SessionLocal
    # Register restoration even on the intentionally failing pre-fix run.
    for key, value in before.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    monkeypatch.setattr(dbmod, "engine", engine)
    monkeypatch.setattr(dbmod, "SessionLocal", factory)
    runpy.run_path(str(Path(__file__).with_name(filename)))
    assert {key: os.environ.get(key) for key in keys} == before
    assert dbmod.engine is engine
    assert dbmod.SessionLocal is factory
