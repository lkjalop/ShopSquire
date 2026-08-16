import asyncio

import pytest

from src.app.services.async_carrier_transport import (
    CarrierDeployment,
    CarrierRequest,
    execute_carrier_request,
)


def _deployment(**changes):
    values = {
        "provider_id": "fixture-carrier", "endpoint": "https://carrier.example/labels",
        "endpoint_identity": "carrier.example", "enabled": True,
    }
    values.update(changes)
    return CarrierDeployment.model_validate(values)


def _request(**changes):
    values = {"operation": "create_label", "request_id": "req-1", "timeout_ms": 100}
    values.update(changes)
    return CarrierRequest.model_validate(values)


def test_carrier_returns_normalized_projection_and_never_raw_body():
    async def send(_deployment, _request):
        return 201, {"secret": "provider-body", "tracking": "TRACK-1"}

    result = asyncio.run(execute_carrier_request(
        _deployment(), _request(), send=send,
        normalize=lambda status, body: {"accepted": status == 201, "tracking": body["tracking"]},
    ))
    assert result.status == "completed"
    assert result.normalized == {"accepted": True, "tracking": "TRACK-1"}
    assert result.raw_provider_body_retained is False
    assert "secret" not in str(result)


def test_carrier_timeout_is_bounded_and_cancels_send():
    cancelled = False

    async def slow(_deployment, _request):
        nonlocal cancelled
        try:
            await asyncio.sleep(1)
            return 200, {}
        except asyncio.CancelledError:
            cancelled = True
            raise

    result = asyncio.run(execute_carrier_request(
        _deployment(), _request(), send=slow, normalize=lambda *_args: {},
    ))
    assert result.status == "timeout" and cancelled is True


def test_caller_cancellation_propagates():
    async def exercise():
        async def slow(_deployment, _request):
            await asyncio.sleep(10)
            return 200, {}

        task = asyncio.create_task(execute_carrier_request(
            _deployment(), _request(timeout_ms=30_000), send=slow,
            normalize=lambda *_args: {},
        ))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())
