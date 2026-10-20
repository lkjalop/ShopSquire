from contextlib import contextmanager
import json

from fastapi import HTTPException
import pytest

from src.app.deps import DummyRedis
from src.app.platform.tenant_context import set_active_tenant_id, reset_active_tenant_id
from src.app.routers import privacy
from tests.privacy_store_fakes import SharedStore


@contextmanager
def tenant(name):
    token = set_active_tenant_id(name)
    try:
        yield
    finally:
        reset_active_tenant_id(token)


@pytest.fixture(autouse=True)
def no_audit_side_effect(monkeypatch):
    monkeypatch.setattr(privacy, 'log_trace_event', lambda **kwargs: None)


def test_consent_and_privacy_request_keys_partition_the_same_subject_by_tenant():
    store = SharedStore()
    with tenant('controller-a'):
        privacy.set_consent('same-subject', privacy.PrivacyConsentPayload(personalization_opt_in=True), store, 'owner')
        consent_key = privacy._consent_key('same-subject')
        request_key = privacy._request_key('same-subject')
    with tenant('controller-b'):
        assert privacy.get_consent('same-subject', store, 'owner')['consent'] == {}
        assert privacy._consent_key('same-subject') != consent_key
        assert privacy._request_key('same-subject') != request_key


@pytest.mark.parametrize('backend', ['unavailable', 'no_acknowledgement'])
def test_a_privacy_request_cannot_be_acknowledged_only_in_process_memory(backend):
    class BrokenStore(SharedStore):
        def set(self, key, value):
            if backend == 'unavailable':
                raise ConnectionError('private backend details must not appear in the response')
            return None
    with pytest.raises(HTTPException) as failure:
        privacy.create_privacy_request('subject-' + backend,
            privacy.PrivacyRequestPayload(request_type='delete'), BrokenStore(), 'owner')
    assert failure.value.status_code == 503
    assert failure.value.detail == 'privacy_backend_unavailable'


def test_unattributed_legacy_consent_does_not_grant_a_tenant_opt_in():
    store = SharedStore()
    store.values['privacy:legacy-subject:consent'] = json.dumps({'personalization_opt_in': True})
    with tenant('new-controller'):
        assert privacy.get_consent('legacy-subject', store, 'owner')['consent'] == {}


def test_process_only_dummy_backend_does_not_pretend_shared_privacy_state_is_available():
    with pytest.raises(HTTPException) as failure:
        privacy.get_consent('subject', DummyRedis(), 'owner')
    assert failure.value.status_code == 503
