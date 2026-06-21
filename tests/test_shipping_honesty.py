"""Track 6 — shipping honesty: no fabricated tracking numbers for stub shipments.

When no real carrier is configured, a "return label" is a stub — the system must say so
(stub=True, status='stub', tracking_number=None) instead of inventing an RR-prefixed tracking
number and recording status='generated' as if a real shipment existed.
"""
from __future__ import annotations

import asyncio

from src.app.services import shipping_stub
from src.app.services.playbook_action_adapters import shipping_action
from src.app.services.shipping_providers import plan_label_record, shipping_readiness

_CARRIER_ENVS = [
    "AUSPOST_API_KEY", "AUSPOST_ACCOUNT_NUMBER",
    "STARTRACK_API_KEY", "STARTRACK_ACCOUNT_NUMBER",
    "EASYPOST_API_KEY", "SHIPSTATION_API_KEY", "SHIPSTATION_API_SECRET",
    "PREFERRED_SHIPPING_PROVIDER",
]


def _clear_carriers(monkeypatch):
    for k in _CARRIER_ENVS:
        monkeypatch.delenv(k, raising=False)


# ── readiness ──
def test_readiness_reports_stub_when_no_carrier(monkeypatch):
    _clear_carriers(monkeypatch)
    r = shipping_readiness()
    assert r["ready"] is False and r["stub"] is True
    assert "no carrier" in r["reason"].lower()
    assert all(v is False for v in r["configured"].values())


def test_readiness_reports_ready_when_carrier_configured(monkeypatch):
    _clear_carriers(monkeypatch)
    monkeypatch.setenv("AUSPOST_API_KEY", "test-key")
    r = shipping_readiness()
    assert r["ready"] is True and r["stub"] is False
    assert r["configured"]["auspost"] is True and r["provider"] == "auspost"


# ── pure plan_label_record ──
def test_plan_stub_when_readiness_stub():
    p = plan_label_record({"stub": True, "reason": "no carrier"}, {"ok": False, "stub": True}, case_id="c1")
    assert p["stub"] is True and p["ok"] is False
    assert p["tracking_number"] is None and p["label_url"] is None and p["status"] == "stub"


def test_plan_generated_when_ready_and_ok():
    p = plan_label_record({"stub": False}, {"ok": True, "label_url": "https://carrier/x.pdf"}, case_id="c1")
    assert p["stub"] is False and p["ok"] is True and p["status"] == "generated"
    assert p["tracking_number"].startswith("RR") and p["label_url"] == "https://carrier/x.pdf"


def test_plan_stub_when_ready_but_create_failed():
    # A configured carrier that returns ok=False must NOT fabricate a tracking number.
    p = plan_label_record({"stub": False}, {"ok": False, "error": "carrier 500"}, case_id="c1")
    assert p["stub"] is True and p["status"] == "stub" and p["tracking_number"] is None
    assert p["reason"] == "carrier 500"


# ── ShippingService end-to-end ──
def test_create_return_label_is_honest_stub(monkeypatch):
    _clear_carriers(monkeypatch)
    out = asyncio.run(shipping_stub.ShippingService().create_return_label("case-y"))
    assert out["stub"] is True and out["ok"] is False
    assert out["tracking_number"] is None and out["status"] == "stub"
    assert "carrier" in out and out["reason"]


def test_create_return_label_real_when_provider_ready(monkeypatch):
    class _FakeProvider:
        name = "fakecarrier"

        def create_label(self, info):
            return {"ok": True, "label_url": "https://carrier/label.pdf"}

    monkeypatch.setattr(shipping_stub, "get_default_shipping_provider", lambda: _FakeProvider())
    monkeypatch.setattr(shipping_stub, "shipping_readiness",
                        lambda: {"ready": True, "stub": False, "reason": "live carrier configured"})
    out = asyncio.run(shipping_stub.ShippingService().create_return_label("case-x"))
    assert out["ok"] is True and out["stub"] is False and out["status"] == "generated"
    assert out["tracking_number"].startswith("RR") and out["carrier"] == "fakecarrier"


# ── playbook adapter ──
def test_shipping_action_stub_is_not_reported_ok(monkeypatch):
    _clear_carriers(monkeypatch)
    res = shipping_action({"type": "create_return_label", "params": {"case_id": "c-1"}}, {})
    assert res["ok"] is False and res["stub"] is True
