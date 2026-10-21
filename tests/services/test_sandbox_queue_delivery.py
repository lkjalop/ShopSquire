"""A sandbox publication needs a real worker transport acknowledgement."""
from uuid import uuid4

from celery import Celery
import pytest

from src.app.services import sandbox_queue


@pytest.fixture()
def publisher(monkeypatch):
    import src.app.workers.celery_app as celery_module
    from src.app.workers import task_runner
    monkeypatch.setenv('CELERY_BROKER_URL','memory://')
    monkeypatch.setenv('CELERY_RESULT_BACKEND','cache+memory://')
    app=Celery('owned-sandbox-'+uuid4().hex,broker='memory://',backend='cache+memory://')
    monkeypatch.setattr(celery_module,'celery_app',app)
    fallback_calls=[]
    def unsupported_fallback(*args,**kwargs):
        fallback_calls.append((args,kwargs))
        return 'identifier-with-no-sandbox-handler'
    monkeypatch.setattr(task_runner,'submit_task',unsupported_fallback)
    try:
        yield app,fallback_calls
    finally:
        app.close()


def test_live_publisher_does_not_require_a_result_subscription(publisher,monkeypatch):
    app,fallback_calls=publisher
    def unavailable_result_backend(*args,**kwargs):
        raise ConnectionError('The result backend is unavailable; the broker is healthy')
    monkeypatch.setattr(app.backend,'on_task_call',unavailable_result_backend)
    trace='owned-sandbox-'+uuid4().hex
    result=sandbox_queue.queue_sandbox_detonation(hypothesis='lolbin_command_sequence',
        tenant_id='tenant-owned',trace_id=trace,decoded_content='inert test payload')
    assert result['queued'] is True and result['path']=='celery'
    assert fallback_calls==[]
    with app.connection_for_read() as connection:
        queue=connection.SimpleQueue('security')
        try:
            message=queue.get(block=False)
            assert message.headers['task']=='sandbox.detonate'
            job=message.payload[1]['job']
            assert job['trace_id']==trace and job['tenant_id']=='tenant-owned'
            assert job['decoded_content']=='inert test payload'
            message.ack()
        finally:
            queue.close()


def test_failed_publisher_cannot_claim_an_unhandled_fallback_was_queued(publisher,monkeypatch):
    app,fallback_calls=publisher
    def failed_publication(*args,**kwargs):
        raise ConnectionError('Owned transport rejected publication before acknowledgement')
    monkeypatch.setattr(app,'send_task',failed_publication)
    result=sandbox_queue.queue_sandbox_detonation(hypothesis='ransomware',tenant_id='tenant-owned')
    assert result['queued'] is False
    assert fallback_calls==[]


def test_low_risk_hypothesis_never_publishes(publisher,monkeypatch):
    app,fallback_calls=publisher
    def forbidden_publication(*args,**kwargs):
        pytest.fail('A low-risk hypothesis must not publish a sandbox task')
    monkeypatch.setattr(app,'send_task',forbidden_publication)
    result=sandbox_queue.queue_sandbox_detonation(hypothesis='benign',tenant_id='tenant-owned')
    assert result['queued'] is False
    assert result['reason']=='hypothesis_not_in_auto_queue_list'
    assert fallback_calls==[]


def test_unscoped_sandbox_job_never_publishes(publisher,monkeypatch):
    app,fallback_calls=publisher
    def forbidden_publication(*args,**kwargs):
        pytest.fail('A sandbox task must have an owned tenant before publication')
    monkeypatch.setattr(app,'send_task',forbidden_publication)
    result=sandbox_queue.queue_sandbox_detonation(hypothesis='ransomware',tenant_id=None)
    assert result['queued'] is False
    assert result['reason']=='tenant_required'
    assert fallback_calls==[]
