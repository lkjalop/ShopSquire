"""Exercise public fetch outcomes through the real HTTPX streaming boundary."""
import copy
import hashlib
from contextlib import contextmanager

import httpx
import pytest
from sqlalchemy import text

from src.app.security.egress_allowlist import EgressBlockedError, scoped_egress_domains
from src.app.services import public_market_source_fetch as market
from tests.services.test_public_market_source_fetch import _db, _recall_body


@contextmanager
def database():
    db = _db()
    engine = db.get_bind()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def transport(monkeypatch):
    state = dict(chunks=[], consumed=0, closed=0, status=200, headers={}, requests=[], clients=[], error=None)

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in state['chunks']:
                state['consumed'] += 1
                yield chunk
            if state['error']:
                raise state['error']

        def close(self):
            state['closed'] += 1

    def response(request):
        state['requests'].append(str(request.url))
        return httpx.Response(state['status'], headers=state['headers'], stream=Stream())

    original = httpx.Client

    def client(**kwargs):
        result = original(transport=httpx.MockTransport(response), **kwargs)
        state['clients'].append(result)
        return result

    monkeypatch.setattr(httpx, 'Client', client)
    with scoped_egress_domains(['www.saferproducts.gov']):
        yield state
    assert state['clients'] and all(client.is_closed for client in state['clients'])
    assert state['closed'] == len(state['requests']) == 1


def budget(monkeypatch, limit):
    registry = copy.deepcopy(market.load_market_source_registry())
    registry['cpsc_recalls']['fetch_profile']['max_response_bytes'] = limit
    monkeypatch.setattr(market, 'load_market_source_registry', lambda: registry)


def fetch(db):
    return market.fetch_public_market_source(db, tenant_id='owned-stream-lab',
        source_id='cpsc_recalls', query={'title': 'dresser'}, enabled=True)


def test_public_fetch_stops_reading_at_the_registry_body_budget(monkeypatch, transport):
    budget(monkeypatch, 2048)
    transport['chunks'] = [b'x' * 1024] * 100
    with database() as db:
        result = fetch(db)
        assert result['outcome'] == 'malformed'
        assert result['error_code'] == 'response_too_large'
        assert result['execution_allowed'] is False
        assert result.get('observations', []) == []
        assert db.scalar(text('SELECT COUNT(*) FROM market_source_fetch_revision')) == 0
    assert transport['consumed'] <= 3


@pytest.mark.parametrize('spare_bytes', [0, 1])
def test_controlled_public_observation_keeps_exact_body_and_revision_at_the_limit(monkeypatch, transport, spare_bytes):
    body = _recall_body()
    budget(monkeypatch, len(body) + spare_bytes)
    transport['chunks'] = [body[:15], body[15:]]
    with database() as db:
        result = fetch(db)
        assert result['outcome'] == 'observed'
        assert len(result['observations']) == 1
        assert result['execution_allowed'] is False
        assert result['authority'] == 'advisory_only'
        assert db.scalar(text('SELECT content_sha256 FROM market_source_fetch_revision')) == hashlib.sha256(body).hexdigest()
        assert db.scalar(text('SELECT revision_number FROM market_source_fetch_revision')) == 1
    assert transport['consumed'] == 2


def test_registry_origin_redirect_is_reported_without_visiting_its_target(transport):
    transport.update(status=302, headers={'location': 'http://127.0.0.1/admin'})
    with database() as db:
        result = fetch(db)
        assert result['outcome'] == 'unavailable'
        assert result['http_status'] == 302
        assert result['execution_allowed'] is False
        assert db.scalar(text('SELECT COUNT(*) FROM market_source_fetch_revision')) == 0
    assert len(transport['requests']) == 1
    assert transport['requests'][0].startswith('https://www.saferproducts.gov/')


def test_stream_failure_does_not_create_an_observation_or_leak_owned_http_resources(transport):
    transport.update(chunks=[b'['], error=httpx.ReadError('owned-stream-fault'))
    with database() as db:
        result = fetch(db)
        assert result['outcome'] == 'unavailable'
        assert result['error_code'] == 'provider_unavailable'
        assert 'owned-stream-fault' not in str(result)
        assert db.scalar(text('SELECT COUNT(*) FROM market_source_fetch_revision')) == 0


def test_denied_network_policy_is_a_distinct_non_authorizing_fetch_outcome():
    def denied(*args):
        raise EgressBlockedError('https://www.saferproducts.gov')

    with database() as db:
        result = market.fetch_public_market_source(db, tenant_id='owned-stream-lab',
            source_id='cpsc_recalls', query={'title': 'dresser'}, enabled=True, transport=denied)
        assert result['outcome'] == 'denied'
        assert result['error_code'] == 'outbound_policy_denied'
        assert result['authority'] == 'advisory_only'
        assert result['execution_allowed'] is False
        assert result.get('observations', []) == []
        assert db.scalar(text('SELECT COUNT(*) FROM market_source_fetch_revision')) == 0
