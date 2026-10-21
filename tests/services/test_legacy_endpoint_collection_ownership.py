"""Collecting an endpoint test module must not replace another test's owner."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('module', [
    'tests.test_admin_overview',
    'tests.test_orders_status',
    'tests.test_order_history_paging',
    'tests.test_security_event_tags',
])
def test_legacy_endpoint_import_preserves_database_owner(module, tmp_path):
    application = Path(__file__).resolve().parents[2]
    working = tmp_path / 'owned-import'
    working.mkdir()
    database_url = 'sqlite+pysqlite:///' + (working / 'owner.sqlite3').as_posix()
    env = {**os.environ, 'PYTHONPATH': str(application), 'DATABASE_URL': database_url,
           'DATABASE_URL_RO': database_url, 'FEATURE_FLAGS_PATH': str(working / 'flags.json'),
           'SECURITY_BLOCK_MODE': '403', 'APP_ENV': 'test'}
    program = '''import importlib
import os
import sys
import src.app.main as main
from src.app.models import db as database
app=main.create_app()
owner=app.state.engine
database.set_engine(owner)
factory=database.SessionLocal
# Match the pytest collection cache: repeated factories return the current app.
main.create_app=lambda:app
before={name:os.environ.get(name) for name in ('DATABASE_URL','DATABASE_URL_RO','SECURITY_BLOCK_MODE')}
importlib.import_module(sys.argv[1])
assert database.get_engine() is owner,'collection_replaced_database_owner'
assert database.SessionLocal is factory,'collection_replaced_session_factory'
assert before=={name:os.environ.get(name) for name in before},'collection_changed_database_or_security_policy'
'''
    result = subprocess.run([sys.executable, '-c', program, module], cwd=working, env=env,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
