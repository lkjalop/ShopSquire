"""Actual child pytest runs must release completed watchdogs and still time out."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]


def child_run(tmp_path, source):
    (tmp_path / 'pytest.ini').write_text('[pytest]\ntimeout = 180\ntimeout_method = thread\n', encoding='utf-8')
    (tmp_path / 'test_child.py').write_text(source, encoding='utf-8')
    (tmp_path / 'conftest.py').write_text('''import importlib.util,json,weakref
from pathlib import Path
import pytest
pytest_plugins = ['tests.owned_timeout_lifecycle'] if importlib.util.find_spec('tests.owned_timeout_lifecycle') else []
timers=[]
settings_seen=[]
@pytest.hookimpl(hookwrapper=True,tryfirst=True,optionalhook=True)
def pytest_timeout_set_timer(item, settings):
    yield
    callback=getattr(item,'cancel_timeout',None)
    cells=dict(zip(callback.__code__.co_freevars,callback.__closure__ or ())) if callback else {}
    if 'timer' in cells:timers.append(weakref.ref(cells['timer'].cell_contents))
    settings_seen.append(dict(timeout=settings.timeout,method=settings.method))
    Path('timer-settings.json').write_text(json.dumps(settings_seen))
def pytest_sessionfinish(session,exitstatus):
    Path('ownership.json').write_text(json.dumps(dict(
        completed_items=len(session.items),retained_callbacks=sum(hasattr(item,'cancel_timeout') for item in session.items),
        retained_timers=sum(reference() is not None for reference in timers),
        active_timers=sum(reference() is not None and reference().is_alive() for reference in timers),
        settings=settings_seen,exitstatus=int(exitstatus))))
''', encoding='utf-8')
    env = {**os.environ, 'PYTHONPATH': str(ROOT)}
    result = subprocess.run([sys.executable, '-m', 'pytest', '-c', 'pytest.ini', '-q', 'test_child.py'],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    summary = tmp_path / 'ownership.json'
    return result, json.loads(summary.read_text()) if summary.exists() else None


@pytest.mark.parametrize('scenario,expected_exit,count', [
    ('passed', 0, 50), ('failed', 1, 1), ('setup_error', 1, 1),
    ('teardown_error', 1, 1), ('skipped', 0, 1),
])
def test_completed_timeout_callbacks_and_timers_are_released(tmp_path, scenario, expected_exit, count):
    source = {
        'passed': 'import pytest\n@pytest.mark.parametrize("number",range(50))\ndef test_normal(number):assert number>=0\n',
        'failed': 'def test_failure():assert False,"controlled assertion failure"\n',
        'setup_error': 'import pytest\n@pytest.fixture\ndef broken():raise RuntimeError("controlled setup failure")\ndef test_setup(broken):pass\n',
        'teardown_error': 'import pytest\n@pytest.fixture\ndef broken():\n yield\n raise RuntimeError("controlled teardown failure")\ndef test_teardown(broken):pass\n',
        'skipped': 'import pytest\n@pytest.mark.skip(reason="controlled skip")\ndef test_skipped():pass\n',
    }[scenario]
    result, summary = child_run(tmp_path, source)
    assert result.returncode == expected_exit, result.stdout + result.stderr
    assert summary is not None
    assert summary['completed_items'] == count
    assert summary['active_timers'] == 0
    assert summary['retained_callbacks'] == 0, 'completed pytest items retain their cancelled watchdog closure'
    assert summary['retained_timers'] == 0
    assert len(summary['settings']) == count
    assert all(row == {'timeout': 180, 'method': 'thread'} for row in summary['settings'])


def test_real_timeout_still_terminates_a_stalled_child(tmp_path):
    result, summary = child_run(tmp_path, '''import threading,pytest
@pytest.mark.timeout(0.2)
def test_stall():
    threading.Event().wait(5)
    print('WATCHDOG_DID_NOT_FIRE',flush=True)
''')
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads((tmp_path / 'timer-settings.json').read_text()) == [{'timeout': 0.2, 'method': 'thread'}]
    assert 'Timeout' in result.stdout + result.stderr
    assert 'Stack of' in result.stdout + result.stderr
    assert 'WATCHDOG_DID_NOT_FIRE' not in result.stdout
    assert summary is None, 'the real thread watchdog must terminate the child before normal teardown'
