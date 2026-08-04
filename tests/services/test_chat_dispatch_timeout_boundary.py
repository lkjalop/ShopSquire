import asyncio
import time

import pytest
from starlette.requests import Request

from src.app.routers.chat import _call_recommend_in_process


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/v1/chat/query",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("testserver", 80),
        "query_string": b"",
    })


def test_sync_facade_can_be_abandoned_at_the_http_deadline(monkeypatch):
    from src.app.services import recommendation_facade

    def blocked_dispatch(*args, **kwargs):
        time.sleep(1.0)
        raise AssertionError("abandoned result must not be observed")

    monkeypatch.setattr(
        recommendation_facade,
        "dispatch_recommendation_core_typed",
        blocked_dispatch,
    )

    async def run():
        return await asyncio.wait_for(
            _call_recommend_in_process(
                _request(),
                {"uid": "timeout-boundary", "query": "show laptops"},
                redis=object(),
                db=object(),
                role="merchant",
            ),
            timeout=0.05,
        )

    started = time.perf_counter()
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(run())
    assert time.perf_counter() - started < 0.3
