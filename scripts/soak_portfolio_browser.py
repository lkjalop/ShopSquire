"""Duration-bound real-API browser replay. This does not certify model/image endurance."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit
if __package__:
    from scripts.soak_resource_sample import snapshot
else:
    from soak_resource_sample import snapshot

RESOURCE_LIMITS={'minimum_available_bytes':1024**3,'maximum_process_rss_bytes':2*1024**3,'maximum_process_handles':5000}


def resource_violation(measurement):
    if measurement['memory_available_bytes']<RESOURCE_LIMITS['minimum_available_bytes']:return 'host_available_memory'
    for process in measurement['application_processes']:
        if process['rss_bytes']>RESOURCE_LIMITS['maximum_process_rss_bytes']:return 'process_rss'
        if process['handles']>RESOURCE_LIMITS['maximum_process_handles']:return 'process_handles'
    return None


def run(*, duration, interval, invoke, fingerprint, report, monotonic=time.monotonic, sleep=time.sleep):
    if duration <= 0 or interval <= 0:
        raise ValueError('positive_duration_and_interval_required')
    started = monotonic()
    source = fingerprint()
    state = dict(status='running', requested_seconds=duration, elapsed_seconds=0,
                 successful_cycles=0, source_digest=source,
                 scope='configured real-API browser replay; no model/image endurance claim',
                 started_at=datetime.now(timezone.utc).isoformat(), sixty_minute_checkpoint=False)
    report(dict(state))
    while monotonic() - started < duration:
        if fingerprint() != source:
            state.update(status='failed', reason='source_changed')
            break
        index = state['successful_cycles'] + 1
        try:
            code = invoke(index)
        except Exception as exc:
            state.update(status='failed', reason='harness_exception', failed_cycle=index,
                         error_type=type(exc).__name__,error=str(exc)[:200])
            break
        state['elapsed_seconds'] = round(monotonic() - started, 3)
        if code != 0:
            state.update(status='failed', reason='browser_cycle_failed', failed_cycle=index, exit_code=code)
            break
        state['successful_cycles'] = index
        state['sixty_minute_checkpoint'] = state['elapsed_seconds'] >= 3600 and index >= 12
        report(dict(state))
        remaining = duration - (monotonic() - started)
        if remaining > 0:
            sleep(min(interval, remaining))
    state['elapsed_seconds'] = round(monotonic() - started, 3)
    state['sixty_minute_checkpoint'] = state['elapsed_seconds'] >= 3600 and state['successful_cycles'] >= 12
    if state['status'] == 'running' and fingerprint() != source:
        state.update(status='failed', reason='source_changed')
    if state['status'] == 'running':
        # Every cycle has a 180-second timeout. Prevent a long idle interval or one
        # slow call from being reported as an endurance run with adequate coverage.
        minimum = max(2, math.floor(duration / (interval + 180)))
        state['status'] = 'passed' if state['successful_cycles'] >= minimum else 'insufficient_cycles'
    report(dict(state))
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration-seconds', type=int, required=True)
    parser.add_argument('--interval-seconds', type=int, default=60)
    parser.add_argument('--base-url', default='http://127.0.0.1:5177')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--api-port',type=int,default=8087)
    parser.add_argument('--spec',action='append')
    parser.add_argument('--net-log', action='store_true', help='Capture Chromium network diagnostics for each local fixture cycle')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node_required')
    environment = dict(os.environ, PLAYWRIGHT_BASE_URL=args.base_url, PLAYWRIGHT_DISABLE_GPU='1')
    command = [node, str(root/'frontend/node_modules/@playwright/test/cli.js'), 'test',
               *(args.spec or ['e2e/portfolio-qualification.spec.ts', 'e2e/case-contract-selection.spec.ts',
               'e2e/electronics-shop-scenario.spec.ts']), '--workers=1', '--retries=0']

    def fingerprint():
        digest = hashlib.sha256()
        for path in (Path(__file__), root/'scripts/soak_resource_sample.py', root/'frontend/playwright.config.ts'):
            digest.update(path.read_bytes())
        for folder in ('src/app', 'frontend/src', 'frontend/e2e', 'config', 'alembic/versions'):
            for path in sorted((root/folder).rglob('*')):
                if path.is_file() and path.suffix in {'.py', '.ts', '.tsx', '.json'}:
                    digest.update(str(path.relative_to(root)).encode())
                    digest.update(path.read_bytes())
        return digest.hexdigest()

    def report(state):
        state['resource_limits']=RESOURCE_LIMITS
        state['specs']=args.spec or ['portfolio-qualification','case-contract-selection','electronics-shop-scenario']
        state['updated_at'] = datetime.now(timezone.utc).isoformat()
        temporary = output/'status.tmp'
        temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
        temporary.replace(output/'status.json')
        with (output/'progress.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(state)+'\n')

    def invoke(index):
        def sample(phase, pid=None):
            measurement = snapshot(browser_parent=pid,ports=(args.api_port,urlsplit(args.base_url).port or 80))
            measurement.update(cycle=index, phase=phase)
            with (output/'resources.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(measurement)+'\n')
            violation=resource_violation(measurement)
            if violation:raise RuntimeError('resource_limit:'+violation)
        sample('before')
        with (output/f'cycle-{index:04d}.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command+[f'--output={output / f"cycle-{index:04d}"}'],
                cwd=root/'frontend', env={**environment, **({'PLAYWRIGHT_NET_LOG_PATH':str(output/f'network-{index:04d}.json')}
                    if args.net_log else {})}, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 180
                while True:
                    sample('during', process.pid)
                    try:
                        code = process.wait(timeout=min(5, max(0.01, deadline-time.monotonic())))
                        sample('after')
                        return code
                    except subprocess.TimeoutExpired:
                        if time.monotonic() >= deadline:
                            raise
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                   stdout=log, stderr=subprocess.STDOUT, check=False)
                else:
                    process.kill()
                process.wait()
                log.write('\nCycle exceeded 180-second bound.\n')
                sample('timeout')
                return 124
            finally:
                if process.poll() is None:
                    if os.name=='nt':
                        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],stdout=log,stderr=subprocess.STDOUT,check=False)
                    else:process.kill()
                    process.wait(timeout=10)
    result = run(duration=args.duration_seconds, interval=args.interval_seconds,
                 invoke=invoke, fingerprint=fingerprint, report=report)
    return 0 if result['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
