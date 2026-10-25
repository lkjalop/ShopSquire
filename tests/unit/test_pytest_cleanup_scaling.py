"""Native child workload bounds collection cost and unreachable handle retention."""
import json
import os
from pathlib import Path
import subprocess
import sys


def test_unchanged_runtime_bounds_full_heap_scans_and_cyclic_handles(tmp_path):
    root = Path(__file__).resolve().parents[2]
    source = '''import gc,json,weakref
from pathlib import Path
import psutil,pytest
LAB=Path(__file__).resolve().parent

@pytest.fixture(scope='module')
def live_owner():
    nodes=[]
    for _ in range(50000):
        node=[]
        node.append(node)
        nodes.append(node)
    borrowed=(LAB/'borrowed-owner').open('w')
    refs=[]
    process=psutil.Process()
    gc.collect()
    baseline=gc.get_stats()[2]['collections']
    baseline_handles=process.num_handles() if hasattr(process,'num_handles') else process.num_fds()
    peaks={'handles':baseline_handles,'unreachable_files':0}
    yield nodes,borrowed,refs,process,peaks
    scans=gc.get_stats()[2]['collections']-baseline
    assert len(nodes)==50000 and nodes[0][0] is nodes[0]
    assert not borrowed.closed
    gc.collect()
    assert all(reference() is None for reference in refs)
    assert not borrowed.closed
    borrowed.close()
    (LAB/'cleanup-summary.json').write_text(json.dumps(dict(cases=len(refs),full_heap_scans=scans,
        peak_unreachable_files=peaks['unreachable_files'],peak_extra_handles=peaks['handles']-baseline_handles,
        live_owner_preserved=True,unreachable_files_released=True)))
    assert scans<8, f'full_heap_scans={scans}; unchanged owner must not require a whole-heap scan per case'
    assert peaks['unreachable_files']<=64
    assert peaks['handles']-baseline_handles<=64

@pytest.mark.parametrize('number',range(64))
def test_bounded_cleanup(number,live_owner):
    nodes,borrowed,refs,process,peaks=live_owner
    assert nodes[-1][0] is nodes[-1] and not borrowed.closed
    assert (number+1)-number==1
    class Cycle:pass
    enabled=gc.isenabled()
    gc.disable()
    try:
        cycle=Cycle()
        cycle.self=cycle
        cycle.file=(LAB/f'cyclic-{number}').open('w')
        refs.append(weakref.ref(cycle.file))
        gc.collect(0)
        del cycle
    finally:
        if enabled:gc.enable()
    peaks['unreachable_files']=max(peaks['unreachable_files'],sum(r() is not None for r in refs))
    handles=process.num_handles() if hasattr(process,'num_handles') else process.num_fds()
    peaks['handles']=max(peaks['handles'],handles)
'''
    (tmp_path / 'test_cleanup_child.py').write_text(source, encoding='utf-8')
    (tmp_path / 'pytest.ini').write_text('[pytest]\ntimeout=180\ntimeout_method=thread\n', encoding='utf-8')
    env = {**os.environ, 'PYTHONPATH': str(root),
        'SECURITY_SERVER_SPAWN': '0', 'E2E_BASE_URL': '',
        'PYTEST_OWNED_SECURITY_DIRECTORY': '',
        'PYTEST_LAST_RUNNING_FILE': str(tmp_path / 'last-running'), 'PYTEST_FAIL_ON_THREAD_LEAK': '1'}
    for name in ('PYTEST_RESULT_STREAM', 'PYTEST_CAPTURE_RESOURCES', 'PYTEST_RESOURCE_GC_STREAM'):
        env.pop(name, None)
    result = subprocess.run([sys.executable, '-m', 'pytest', '-p', 'tests.conftest',
        '-c', str(tmp_path / 'pytest.ini'), '-q', str(tmp_path / 'test_cleanup_child.py')], cwd=root,
        env=env, capture_output=True, text=True, timeout=150)
    summary_path = tmp_path / 'cleanup-summary.json'
    assert summary_path.exists(), result.stdout + result.stderr
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    assert summary['cases'] == 64
    assert summary['live_owner_preserved'] and summary['unreachable_files_released']
    assert result.returncode == 0, (summary, result.stdout, result.stderr)
