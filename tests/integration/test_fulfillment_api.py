"""Step 6 — the /fulfillment/cases API over the tested workflow: HTTP maps cleanly to transitions,
the actor is resolved from role/uid, illegal commands return 409, demo replies are gated, and the
buyer view is redacted."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())
_BASE = "/api/v1/fulfillment/cases"


def _open():
    r = client.post(_BASE, json={"uid": "u1", "trace_id": "T-API-1"})
    assert r.status_code == 200, r.text
    return r.json()["case_id"]


def test_open_assess_commit_flow_over_http():
    cid = _open()
    r = client.post(f"{_BASE}/{cid}/assess", json={"requested_qty": 10, "in_stock": 4, "item_ref": "SKU-1"})
    assert r.status_code == 200 and r.json()["state"] == "AWAITING_BUYER_COMMITMENT"
    # GATE 1: the buyer commits (no operator role needed)
    r = client.post(f"{_BASE}/{cid}/commit", json={"uid": "u1"})
    assert r.status_code == 200 and r.json()["state"] == "COMMITTED"
    # read back
    assert client.get(f"{_BASE}/{cid}").json()["state"] == "COMMITTED"
    j = client.get(f"{_BASE}/{cid}/journey").json()["journey"]
    assert [e["event"] for e in j][:3] == ["case_opened", "availability_assessed", "request_buyer_commitment"]


def test_illegal_command_returns_409():
    cid = _open()
    # cannot dispatch from NEW — the workflow rejects, the API surfaces 409
    r = client.post(f"{_BASE}/{cid}/dispatch", json={"content_hash": "x"})
    assert r.status_code == 409


def test_demo_reply_gated_off_by_default():
    cid = _open()
    r = client.post(f"{_BASE}/{cid}/demo-reply", json={"scenario": "full_quote", "requested_qty": 6})
    assert r.status_code == 403  # FULFILLMENT_DEMO_ENABLED is off


def test_buyer_view_redacts_supplier_private_fields(monkeypatch):
    monkeypatch.setenv("FULFILLMENT_DEMO_ENABLED", "1")
    cid = _open()
    client.post(f"{_BASE}/{cid}/assess", json={"requested_qty": 10, "in_stock": 4, "item_ref": "SKU-1"})
    client.post(f"{_BASE}/{cid}/commit", json={"uid": "u1"})
    # draft (agent) — needs an approved supplier; this may no-op to NO_APPROVED_SUPPLIER without seeded
    # suppliers, which is fine: the point is the buyer view never exposes a draft body if one exists.
    client.post(f"{_BASE}/{cid}/draft-quote", json={"item_ref": "SKU-1", "quantity": 6})
    buyer = client.get(f"{_BASE}/{cid}", params={"view": "buyer"}).json()
    assert "draft" not in buyer["state_json"] and "inbound" not in buyer["state_json"]


def test_unknown_case_404():
    assert client.get(f"{_BASE}/does-not-exist").status_code == 404


def test_po_endpoints_wired_and_guard_illegal_state():
    # propose/execute/complete are registered and surface the workflow's transition guard (409 from NEW,
    # not a 404 unrouted) — the happy-path advance itself is proven by the service-level journey test.
    cid = _open()
    for ep, payload in (("propose-po", None), ("execute-po", {}), ("complete", None)):
        r = client.post(f"{_BASE}/{cid}/{ep}", json=payload)
        assert r.status_code == 409, (ep, r.status_code, r.text)


def test_po_endpoints_on_unknown_case_404():
    assert client.post(f"{_BASE}/nope/propose-po").status_code == 404
    assert client.post(f"{_BASE}/nope/execute-po", json={}).status_code == 404
    assert client.post(f"{_BASE}/nope/complete").status_code == 404


def test_economics_endpoint_operator_and_empty_before_quote():
    # operator route is wired and returns 200; with no validated quote yet it invents nothing → {}
    cid = _open()
    r = client.get(f"{_BASE}/{cid}/economics")
    assert r.status_code == 200 and r.json()["economics"] == {}


def test_by_trace_links_case_to_decision_trace():
    # a case opened with a trace_id is resolvable by that trace (the DecisionTrace ↔ journey link)
    r = client.post(_BASE, json={"uid": "u1", "trace_id": "T-LINK-42"})
    cid = r.json()["case_id"]
    r2 = client.get(f"{_BASE}/by-trace/T-LINK-42")
    assert r2.status_code == 200 and r2.json()["case_id"] == cid and r2.json()["trace_id"] == "T-LINK-42"


def test_by_trace_404_when_no_case():
    assert client.get(f"{_BASE}/by-trace/no-such-trace-xyz").status_code == 404


def test_market_replay_gated_then_advances(monkeypatch):
    # gated off by default
    assert client.post("/api/v1/fulfillment/replay/advance", params={"day": 7}).status_code == 403
    # on → load + analyze the synthetic curve; findings appear
    monkeypatch.setenv("FULFILLMENT_DEMO_ENABLED", "1")
    client.post("/api/v1/fulfillment/replay/reset")
    r = client.post("/api/v1/fulfillment/replay/advance", params={"day": 7})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"]["label"] == "SYNTHETIC REPLAY"
    types = {f["type"] for f in body["state"]["findings"]}
    assert "demand_shift" in types or "inventory_demand_mismatch" in types
    client.post("/api/v1/fulfillment/replay/reset")
