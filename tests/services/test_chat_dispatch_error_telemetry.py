import asyncio
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from starlette.requests import Request

from src.app.routers.chat import _call_recommend_in_process


def request():
    result = Request({'type': 'http', 'method': 'POST', 'path': '/api/v1/chat/query',
                      'headers': [], 'client': ('127.0.0.1', 1234)})
    result.state.operator_identity = SimpleNamespace(tenant_id='dispatch-tenant')
    return result


@pytest.mark.parametrize('failure', [RuntimeError, ValueError])
@pytest.mark.parametrize('metrics_unavailable', [False, True])
def test_unexpected_facade_failure_is_counted_without_replacing_the_primary_error(monkeypatch, failure, metrics_unavailable):
    primary = failure('PRIVATE_EXCEPTION_DETAIL')
    records = []

    def fail(*_args, **_kwargs):
        raise primary

    def metric(**fields):
        records.append(fields)
        if metrics_unavailable:
            raise OSError('controlled telemetry outage')

    monkeypatch.setattr('src.app.services.recommendation_facade.dispatch_recommendation_core_typed', fail)
    monkeypatch.setattr('src.app.observability.metrics.record_recommendation_dispatch', metric)
    with pytest.raises(failure) as caught:
        asyncio.run(_call_recommend_in_process(request(),
            {'uid': 'dispatch-buyer', 'query': 'quote 20 units', 'turn_intent': 'PROCUREMENT'},
            redis=object(), db=object(), role='merchant'))
    assert caught.value is primary
    assert records == [{'outcome': 'error', 'lane': 'PROCUREMENT', 'reason': 'core_error'}]
    assert 'PRIVATE_EXCEPTION_DETAIL' not in str(records)


def test_explicit_http_denial_keeps_its_status_without_becoming_an_unexpected_error(monkeypatch):
    records = []

    def deny(*_args, **_kwargs):
        raise HTTPException(status_code=403, detail='controlled denial')

    monkeypatch.setattr('src.app.services.recommendation_facade.dispatch_recommendation_core_typed', deny)
    monkeypatch.setattr('src.app.observability.metrics.record_recommendation_dispatch', lambda **fields: records.append(fields))
    status, body = asyncio.run(_call_recommend_in_process(request(), {'uid': 'dispatch-buyer', 'query': 'restricted'},
        redis=object(), db=object(), role='merchant'))
    assert status == 403 and body == {'detail': 'controlled denial'}
    assert records == []
