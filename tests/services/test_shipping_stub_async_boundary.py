import asyncio
import time

from src.app.services import shipping_stub


def test_carrier_sdk_call_does_not_block_event_loop(monkeypatch):
    class SlowProvider:
        name = "fixture-carrier"

        def create_label(self, _payload):
            time.sleep(0.05)
            return {"ok": False, "stub": True, "error": "fixture"}

    monkeypatch.setattr(shipping_stub, "get_default_shipping_provider", SlowProvider)
    monkeypatch.setattr(
        shipping_stub,
        "shipping_readiness",
        lambda: {"ready": False, "stub": True, "reason": "fixture"},
    )

    async def exercise():
        task = asyncio.create_task(shipping_stub.ShippingService().create_return_label("case-1"))
        await asyncio.sleep(0.005)
        assert task.done() is False
        return await task

    result = asyncio.run(exercise())
    assert result["stub"] is True
