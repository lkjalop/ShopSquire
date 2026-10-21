"""An actual API fixture must release its owner before the next module runs."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize('module', [
    'tests.api.test_complaints_pipeline_smoke',
    'tests.api.test_pipeline_e2e_fraud_and_warehouse',
    'tests.api.test_redteam_storefront_security_wiring',
    'tests.api.test_support_complaints_security',
])
def test_api_fixture_releases_database_and_application_owner(module, tmp_path):
    application = Path(__file__).resolve().parents[2]
    working = tmp_path / 'owned-lifetime'
    working.mkdir()
    first = working / 'test_first_fixture.py'
    second = working / 'test_second_owner.py'
    first.write_text('from ' + module + ''' import client
from sqlalchemy import text
def test_actual_fixture_has_a_working_database(client):
    with client.app.state.engine.connect() as db:
        assert db.scalar(text('SELECT 1')) == 1
''', encoding='utf-8')
    second.write_text('''def test_next_module_retains_its_original_owner(request):
    import os
    from src.app.models import db as database
    from tests import conftest as runtime
    original=request.config._owned_lifetime_baseline
    assert database.get_engine() is original['engine'],'previous_fixture_retained_database_owner'
    assert database.SessionLocal is original['factory'],'previous_fixture_retained_session_factory'
    assert {name:os.environ.get(name) for name in original['environment']}==original['environment'],'previous_fixture_retained_database_environment'
    assert set(runtime._SINGLETONS)==original['applications'],'previous_fixture_retained_application'
''', encoding='utf-8')
    basetemp = working / 'pytest-tmp'
    assert basetemp.resolve().is_relative_to(tmp_path.resolve()) and not basetemp.exists()
    env = {**os.environ, 'PYTHONPATH': str(application),
           'PYTEST_RESULT_STREAM': str(working / 'child-phases.jsonl'),
           'PYTEST_LAST_RUNNING_FILE': str(working / 'child-last-running.txt'),
           'FEATURE_FLAGS_PATH': str(working / 'flags.json')}
    program = '''import os
import sys
import pytest
from tests import conftest as runtime
class Capture:
    @pytest.hookimpl(trylast=True)
    def pytest_sessionstart(self,session):
        from src.app.models import db as database
        session.config._owned_lifetime_baseline=dict(engine=database.get_engine(),factory=database.SessionLocal,
            environment={name:os.environ.get(name) for name in ('DATABASE_URL','DATABASE_URL_RO')},
            applications=set(runtime._SINGLETONS))
raise SystemExit(pytest.main(sys.argv[1:],plugins=[runtime,Capture()]))
'''
    result = subprocess.run([sys.executable, '-c', program, str(first), str(second), '-q',
                             '--basetemp=' + str(basetemp)], cwd=application, env=env,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
