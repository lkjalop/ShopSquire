"""Signed worker delivery and a real loopback transport that never responds."""
from concurrent.futures import ThreadPoolExecutor
import os
import socketserver
import threading
from uuid import uuid4

from celery import Celery
from celery.contrib.testing.worker import start_worker
import pytest

from src.app.services import sandbox_queue


@pytest.mark.integration
def test_signed_sandbox_publication_reaches_worker_without_result_subscription(monkeypatch):
    import src.app.workers.celery_app as celery_module
    monkeypatch.setenv('CELERY_BROKER_URL',os.getenv('TEST_CELERY_BROKER_URL','memory://'))
    monkeypatch.setenv('CELERY_RESULT_BACKEND','redis://127.0.0.1:1/0')
    monkeypatch.setenv('CELERY_TASK_SIGNING_ENABLED','1')
    monkeypatch.setenv('CELERY_HMAC_KEY','owned-sandbox-publisher-test-key')
    monkeypatch.setenv('ENVIRONMENT','production')
    app=celery_module.make_celery('owned-sandbox-'+uuid4().hex)
    app.conf.update(imports=(),beat_schedule={})
    monkeypatch.setattr(celery_module,'celery_app',app)
    task_name='owned.sandbox.'+uuid4().hex
    monkeypatch.setattr(sandbox_queue,'_SANDBOX_TASK_NAME',task_name)
    received=threading.Event()
    jobs=[]
    def forbidden_result_subscription(*args,**kwargs):
        pytest.fail('Publishing a sandbox intent must not connect to the result backend')
    monkeypatch.setattr(app.backend,'on_task_call',forbidden_result_subscription)
    @app.task(name=task_name,ignore_result=True)
    def observe(job):
        jobs.append(job)
        received.set()
    trace='owned-trace-'+uuid4().hex
    try:
        with start_worker(app,perform_ping_check=False,pool='solo',queues=['security'],shutdown_timeout=10):
            result=sandbox_queue.queue_sandbox_detonation(hypothesis='ransomware',
                tenant_id='tenant-owned',trace_id=trace,attachment_hashes=['inert-owned-hash'])
            assert result['queued'] is True and result['path']=='celery'
            assert received.wait(timeout=10),'The authenticated worker did not receive the published intent'
        assert len(jobs)==1 and jobs[0]['tenant_id']=='tenant-owned'
        assert jobs[0]['trace_id']==trace
        assert jobs[0]['attachment_hashes']==['inert-owned-hash']
    finally:
        app.close()


def test_unresponsive_loopback_broker_returns_unconfirmed_before_release(monkeypatch):
    import src.app.workers.celery_app as celery_module
    release=threading.Event()
    entered=threading.Event()
    class Blackhole(socketserver.BaseRequestHandler):
        def handle(self):
            entered.set()
            release.wait(timeout=15)
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads=True
    with Server(('127.0.0.1',0),Blackhole) as server:
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.05},daemon=True)
        worker.start()
        broker=f'redis://127.0.0.1:{server.server_address[1]}/0'
        monkeypatch.setenv('CELERY_BROKER_URL',broker)
        monkeypatch.setenv('CELERY_RESULT_BACKEND','cache+memory://')
        app=Celery('owned-unresponsive-'+uuid4().hex,broker=broker,backend='cache+memory://')
        monkeypatch.setattr(celery_module,'celery_app',app)
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future=executor.submit(sandbox_queue.queue_sandbox_detonation,
                    hypothesis='ransomware',tenant_id='tenant-owned')
                try:
                    result=future.result(timeout=5)
                    assert entered.is_set() and not release.is_set()
                    assert result['queued'] is False
                    assert result['delivery_status']=='unconfirmed'
                finally:
                    release.set()
        finally:
            release.set()
            server.shutdown()
            worker.join(timeout=2)
            app.close()
            assert not worker.is_alive()
