"""Run the owned, offline image API/detector/React gate from a checkout.

Requires the pinned Python test/vision dependencies, frontend npm dependencies
and the matching pytest-playwright browser. No model download is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.image_security_fixtures import generate_steg_corpus
from tests.owned_security_runtime import disable_message_connectors


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-directory', type=Path)
    parser.add_argument('--browser-cache', type=Path)
    args = parser.parse_args()
    output = (args.artifact_directory or ROOT/'.artifacts'/('image-profile-'+uuid.uuid4().hex)).resolve()
    output.mkdir(parents=True, exist_ok=False)
    corpus = output/'corpus'
    generate_steg_corpus(corpus)
    env = os.environ.copy()
    disable_message_connectors(env)
    env.update(APP_ENV='test', PYTHONUTF8='1', PYTHONIOENCODING='utf-8', PYTHONPATH=str(ROOT),
        DISABLE_PLAYWRIGHT_TESTS='0', PYTEST_STEG_CORPUS_DIRECTORY=str(corpus),
        TEST_USE_PROVIDED_DATABASE='0', SECURITY_SERVER_SPAWN='0',
        TEST_BYPASS_POLICY_GATE='0', TEST_TOLERANT_GET_ERRORS='0',
        CV_STEG_DETECT_ENABLED='1', CV_PROVIDER='basic', CV_OCR_PROVIDER='disabled', CV_VISION_ENABLED='0',
        CUDA_VISIBLE_DEVICES='-1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        VLM_WARMUP_ON_START='0', CV_WARMUP_ON_START='0', EXTERNAL_RESEARCH_ENABLED='0',
        PAYMENT_EXECUTION_ENABLED='0', ALLOW_DEMO_CHECKOUT='0', TASK_CONSUMER_ENABLED='0',
        FULFILLMENT_SUPPLIER_TRANSPORT='sandbox', FULFILLMENT_PO_TRANSPORT='sandbox',
        MERCHANT_API_KEY='local-merchant-key', OWNER_API_KEY='local-owner-key', DEVELOPER_API_KEY='local-developer-key')
    for key in ('OLLAMA_URL', 'OLLAMA_BASE_URL', 'OLLAMA_HOST'):
        env[key] = 'http://127.0.0.1:1'
    for key in ('REDIS_URL', 'SCHEDULER_REDIS_URL', 'RQ_REDIS_URL', 'CELERY_BROKER_URL', 'CELERY_RESULT_BACKEND'):
        env[key] = 'redis://127.0.0.1:1/0'
    for key in ('REDIS_URL_REF', 'DATABASE_URL_REF', 'OPENAI_API_KEY', 'OPENAI_API_KEY_REF',
                'STRIPE_API_KEY', 'STRIPE_API_KEY_REF', 'PAYPAL_CLIENT_ID', 'PAYPAL_CLIENT_ID_REF',
                'PAYPAL_CLIENT_SECRET', 'PAYPAL_CLIENT_SECRET_REF', 'ERP_PO_URL', 'ERP_API_KEY'):
        env[key] = ''
    if args.browser_cache:
        cache = args.browser_cache.resolve(strict=True)
        if not cache.is_dir():
            parser.error('--browser-cache must be a directory')
        env['PLAYWRIGHT_BROWSERS_PATH'] = str(cache)
    command = [sys.executable, '-m', 'pytest',
        'tests/pw/test_vision_upload_perf.py', 'tests/pw/test_steg_image_assessment.py',
        '-q', '--timeout=180', '--junitxml='+str(output/'tests.xml'), '--tracing=retain-on-failure']
    inputs = ['scripts/run_image_security_profile.py', 'tests/image_security_fixtures.py',
        'tests/pw/conftest.py', 'tests/pw/test_vision_upload_perf.py', 'tests/pw/test_steg_image_assessment.py',
        'src/app/services/cv_tier2_pipeline.py', 'src/app/services/cv_analysis_cache.py',
        'frontend/vite.config.ts', 'frontend/package-lock.json']
    fingerprints = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in inputs}
    started = time.monotonic()
    owned = {}
    peaks = dict(process_rss_bytes=0, process_handles_or_fds=0)
    violation = None
    process = None
    code = None
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        with (output/'tests.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), start_new_session=os.name != 'nt')
            (output/'owner.json').write_text(json.dumps(dict(pid=process.pid, command=command)), encoding='utf-8')
            while process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    for child in [parent, *parent.children(recursive=True)]:
                        try:
                            owned[(child.pid, child.create_time())] = child
                            peaks['process_rss_bytes'] = max(peaks['process_rss_bytes'], child.memory_info().rss)
                            descriptors = child.num_handles() if os.name == 'nt' else child.num_fds()
                            peaks['process_handles_or_fds'] = max(peaks['process_handles_or_fds'], descriptors)
                        except psutil.NoSuchProcess:
                            pass
                except psutil.NoSuchProcess:
                    pass
                if peaks['process_rss_bytes'] > 2*1024**3:
                    violation = 'process_rss_over_2GiB'
                elif peaks['process_handles_or_fds'] > 5000:
                    violation = 'process_handles_or_fds_over_5000'
                elif psutil.virtual_memory().available < 1024**3:
                    violation = 'host_free_memory_under_1GiB'
                elif time.monotonic()-started > 900:
                    violation = 'profile_deadline_900s'
                if violation:
                    break
                time.sleep(0.25)
            if not violation:
                code = process.wait(timeout=5)
    finally:
        live = [child for child in owned.values() if child.is_running()]
        for child in live:
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(live, timeout=5)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        _, survivors = psutil.wait_procs(alive, timeout=5)
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                code = process.wait(timeout=5)
        if os.name == 'nt':
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
    counts = {}
    if (output/'tests.xml').is_file():
        suites = list(ET.parse(output/'tests.xml').iter('testsuite'))
        counts = {key: sum(int(s.get(key, 0)) for s in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    changes = [name for name, digest in fingerprints.items() if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
    passed = code == 0 and counts.get('tests', 0)>0 and not any(counts.get(key) for key in ('failures', 'errors', 'skipped'))
    receipt = dict(exit_code=code, counts=counts, resource_violation=violation, peaks=peaks,
        elapsed_seconds=round(time.monotonic()-started, 3), changed_profile_inputs=changes,
        profile_input_sha256=fingerprints, owned_surviving_pids=[child.pid for child in survivors],
        model_profile='CPU/offline deterministic inputs; real-model certification is separate',
        policy_gate_bypass=False, tolerant_get_errors=False,
        green=bool(passed and not violation and not changes and not survivors))
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(dict(artifact_directory=str(output), **receipt)), flush=True)
    return 0 if receipt['green'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(run())
