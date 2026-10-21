"""The clear response must expose the same restorable state as a fresh cart read."""
import pytest

from src.app.deps import get_redis
from tests.test_cart_stock_gates import client_with_stock, _FakeRedis


@pytest.fixture
def clear_client(client_with_stock, monkeypatch):
    # This inherited fixture shares one in-memory SQLite connection. Keep its
    # unrelated telemetry synchronous; native file-backed browser coverage runs
    # the real background observer and Redis separately.
    monkeypatch.setenv('SECURITY_OBSERVER_SYNC', '1')
    cache = _FakeRedis()
    client_with_stock.app.dependency_overrides[get_redis] = lambda: cache
    try:
        yield client_with_stock, cache
    finally:
        client_with_stock.app.dependency_overrides.pop(get_redis, None)


def seed_lines(client, uid):
    lines = [{'sku': 'SKU-INSTOCK-5', 'quantity': 2}, {'sku': 'SKU-INSTOCK-1', 'quantity': 1}]
    for line in lines:
        response = client.post('/api/v1/cart/items', json={'uid': uid, **line})
        assert response.status_code == 200, response.text
    return lines


def test_clear_response_exposes_two_line_snapshot_and_restore_is_exact(clear_client):
    client, _ = clear_client
    uid = 'clear-response-with-undo'
    lines = seed_lines(client, uid)
    cleared = client.post('/api/v1/cart/clear', params={'uid': uid})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()['items'] == []
    assert cleared.json().get('undo') == {'available': True, 'count': 2}
    fresh = client.get('/api/v1/cart', params={'uid': uid})
    assert fresh.status_code == 200
    assert fresh.json()['undo'] == cleared.json()['undo']
    restored = client.post('/api/v1/cart/undo', params={'uid': uid})
    assert restored.status_code == 200, restored.text
    assert [{'sku': row['sku'], 'quantity': row['quantity']} for row in restored.json()['items']] == lines
    assert client.post('/api/v1/cart/undo', params={'uid': uid}).status_code == 404


def test_empty_clear_response_does_not_advertise_an_old_snapshot(clear_client):
    client, _ = clear_client
    uid = 'clear-response-no-stale-undo'
    seed_lines(client, uid)
    assert client.post('/api/v1/cart/clear', params={'uid': uid}).status_code == 200
    empty = client.post('/api/v1/cart/clear', params={'uid': uid})
    assert empty.status_code == 200
    assert empty.json().get('undo') == {'available': False, 'count': 0}
    assert client.post('/api/v1/cart/undo', params={'uid': uid}).status_code == 404


def test_failed_snapshot_write_is_not_presented_as_restorable(clear_client, monkeypatch):
    client, cache = clear_client
    uid = 'clear-response-cache-unavailable'
    seed_lines(client, uid)

    def unavailable(*args, **kwargs):
        raise ConnectionError('owned test cache unavailable')

    monkeypatch.setattr(cache, 'setex', unavailable)
    cleared = client.post('/api/v1/cart/clear', params={'uid': uid})
    assert cleared.status_code == 200
    assert cleared.json()['items'] == []
    assert cleared.json().get('undo') == {'available': False, 'count': 0}


def test_failed_snapshot_write_cannot_reuse_a_different_older_cart(clear_client, monkeypatch):
    client, cache = clear_client
    uid = 'clear-response-stale-cache'
    stashed = client.post('/api/v1/cart/undo/stash', json={
        'uid': uid, 'items': [{'sku': 'SKU-OOS', 'quantity': 4}],
    })
    assert stashed.status_code == 200
    seed_lines(client, uid)

    def unavailable(*args, **kwargs):
        raise ConnectionError('owned test snapshot write unavailable')

    monkeypatch.setattr(cache, 'setex', unavailable)
    cleared = client.post('/api/v1/cart/clear', params={'uid': uid})
    assert cleared.status_code == 200
    assert cleared.json().get('undo') == {'available': False, 'count': 0}
    assert client.get('/api/v1/cart', params={'uid': uid}).json()['undo']['available'] is False
    assert client.post('/api/v1/cart/undo', params={'uid': uid}).status_code == 404


def test_cache_cannot_invalidate_old_snapshot_leaves_the_cart_unchanged(clear_client, monkeypatch):
    client, cache = clear_client
    uid = 'clear-response-invalidation-unavailable'
    lines = seed_lines(client, uid)

    def unavailable(*args, **kwargs):
        raise ConnectionError('owned test snapshot invalidation unavailable')

    monkeypatch.setattr(cache, 'delete', unavailable)
    cleared = client.post('/api/v1/cart/clear', params={'uid': uid})
    assert cleared.status_code == 503
    assert cleared.json()['detail'] == 'cart_snapshot_unavailable'
    fresh = client.get('/api/v1/cart', params={'uid': uid})
    assert [{'sku': row['sku'], 'quantity': row['quantity']} for row in fresh.json()['items']] == lines
