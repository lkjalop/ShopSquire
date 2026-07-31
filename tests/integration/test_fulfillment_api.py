"""Step 6 — the /fulfillment/cases API over the tested workflow: HTTP maps cleanly to transitions,
the actor is resolved from role/uid, illegal commands return 409, demo replies are gated, and the
buyer view is redacted."""
from __future__ import annotations

import time

import jwt
import pytest
import uuid
from fastapi.testclient import TestClient

from src.app.main import app
from tests.utils import default_headers

client = TestClient(app, headers=default_headers())
_BASE = "/api/v1/fulfillment/cases"


def _open():
    r = client.post(_BASE, json={"uid": "u1", "trace_id": f"T-API-{uuid.uuid4()}"})
    assert r.status_code == 200, r.text
    return r.json()["case_id"]


def _buyer_token(secret: str, subject: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": subject,
            "typ": "access",
            "iss": "shopsquire",
            "aud": "shopsquire-api",
            "iat": now,
            "exp": now + 300,
        },
        secret,
        algorithm="HS256",
    )


def test_strict_buyer_boundary_hides_foreign_cases(monkeypatch):
    cid = _open()
    monkeypatch.setenv("BUYER_IDENTITY_MODE", "strict")
    monkeypatch.setenv("JWT_SIGNING_KEY", "buyer-boundary-test")

    assert client.get(f"{_BASE}/{cid}").status_code == 401
    own = _buyer_token("buyer-boundary-test", "u1")
    assert client.get(
        f"{_BASE}/{cid}", headers={"Authorization": f"Bearer {own}"}
    ).status_code == 200

    foreign = _buyer_token("buyer-boundary-test", "u2")
    assert client.get(
        f"{_BASE}/{cid}", headers={"Authorization": f"Bearer {foreign}"}
    ).status_code == 404
    assert client.post(
        f"{_BASE}/{cid}/commit",
        headers={"Authorization": f"Bearer {own}"},
        json={"uid": "u2"},
    ).status_code == 403


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


def test_commit_auto_drafts_internal_rfq_when_flag_enabled(monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTO_DRAFT_ON_COMMIT", "1")
    from src.app.models.db import db_session
    from src.app.services.supplier_catalog import ensure_supplier_coverage
    with db_session() as db:
        ensure_supplier_coverage(db)

    cid = _open()
    r = client.post(f"{_BASE}/{cid}/assess", json={"requested_qty": 10, "in_stock": 4, "item_ref": "GAM-0002"})
    assert r.status_code == 200 and r.json()["state"] == "AWAITING_BUYER_COMMITMENT"
    r = client.post(f"{_BASE}/{cid}/commit", json={"uid": "u1"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["state"] == "QUOTE_DRAFTED"
    assert "draft" not in body["state_json"]

    r = client.get(f"{_BASE}/{cid}/operator-view")
    assert r.status_code == 200
    draft = r.json()["state_json"]["draft"]
    assert draft["commercial_scope"]["item_ref"] == "GAM-0002"
    assert draft["commercial_scope"]["quantity"] == 6
    assert draft["recipient_domain"] == "creatorfleet.example"
    assert draft["content_hash"]

    buyer = client.get(f"{_BASE}/{cid}").json()["state_json"]
    assert "draft" not in buyer
    assert buyer["procurement_trace"]["quantity"] == 6
    assert buyer["procurement_trace"]["channel"]
    assert "recipient_email" not in buyer["procurement_trace"]
    assert "body" not in buyer["procurement_trace"]
    assert "supplier_terms" not in buyer["procurement_trace"]


def test_commit_records_pending_retry_when_internal_draft_fails(monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTO_DRAFT_ON_COMMIT", "1")

    def _fail_draft(*args, **kwargs):
        raise RuntimeError("synthetic draft failure")

    monkeypatch.setattr("src.app.routers.fulfillment_cases.fdraft.draft_and_record", _fail_draft)
    monkeypatch.setattr("src.app.services.decision_log.log_trace_event", lambda **kwargs: None)
    cid = _open()
    assessed = client.post(
        f"{_BASE}/{cid}/assess",
        json={"requested_qty": 10, "in_stock": 4, "item_ref": "SKU-RETRY-1"},
    )
    assert assessed.status_code == 200

    response = client.post(f"{_BASE}/{cid}/commit", json={"uid": "u1"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "COMMITTED"
    assert body["draft_status"]["status"] == "pending"
    assert "synthetic draft failure" in body["draft_status"]["last_error"]


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


def test_rfq_fanout_endpoint_wired_and_shaped():
    # operator route registered; with no seeded approved suppliers in the test DB it returns 0 drafts
    # (never 404/unrouted) and the documented shape.
    cid = _open()
    client.post(f"{_BASE}/{cid}/assess", json={"requested_qty": 10, "in_stock": 4, "item_ref": "SKU-1"})
    client.post(f"{_BASE}/{cid}/commit", json={"uid": "u1"})
    r = client.get(f"{_BASE}/{cid}/rfq-fanout", params={"top_n": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["item_ref"] == "SKU-1" and body["top_n"] == 3 and isinstance(body["drafts"], list)
    assert client.get(f"{_BASE}/nope/rfq-fanout").status_code == 404


def test_compare_quotes_endpoint_ranks_and_recommends():
    cid = _open()
    quotes = [
        {"supplier_ref": "A", "unit_price_cents": 120000, "lead_time_days": 10, "reliability": 0.95},
        {"supplier_ref": "B", "unit_price_cents": 100000, "lead_time_days": 20, "reliability": 0.80},
        {"supplier_ref": "C", "unit_price_cents": 110000, "lead_time_days": 7, "reliability": 0.90},
    ]
    r = client.post(f"{_BASE}/{cid}/compare-quotes", json={"quotes": quotes})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["considered"] == 3 and body["recommended"]["supplier_ref"] == "C"
    assert client.post(f"{_BASE}/nope/compare-quotes", json={"quotes": quotes}).status_code == 404


def test_decision_intelligence_route_reports_unmaterialized_evidence_explicitly():
    cid = _open()
    response = client.get(f"{_BASE}/{cid}/decision-intelligence")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "status": "not_materialized",
        "context": None,
        "proposal": None,
        "comparison": None,
    }


def test_by_trace_links_case_to_decision_trace():
    # a case opened with a trace_id is resolvable by that trace (the DecisionTrace ↔ journey link)
    r = client.post(_BASE, json={"uid": "u1", "trace_id": "T-LINK-42"})
    cid = r.json()["case_id"]
    r2 = client.get(f"{_BASE}/by-trace/T-LINK-42")
    assert r2.status_code == 200 and r2.json()["case_id"] == cid and r2.json()["trace_id"] == "T-LINK-42"


def test_by_trace_query_string_cannot_escalate_to_operator_view(monkeypatch):
    monkeypatch.setenv("FULFILLMENT_AUTO_DRAFT_ON_COMMIT", "1")
    from src.app.models.db import db_session
    from src.app.services.supplier_catalog import ensure_supplier_coverage
    with db_session() as db:
        ensure_supplier_coverage(db)
    trace_id = f"T-REDACT-{uuid.uuid4()}"
    cid = client.post(_BASE, json={"uid": "u1", "trace_id": trace_id}).json()["case_id"]
    client.post(f"{_BASE}/{cid}/assess", json={"requested_qty": 10, "in_stock": 4, "item_ref": "GAM-0002"})
    client.post(f"{_BASE}/{cid}/commit", json={"uid": "u1"})

    buyer = client.get(f"{_BASE}/by-trace/{trace_id}/all?view=operator").json()["cases"][0]

    assert "draft" not in buyer["state_json"]
    assert buyer["state_json"]["procurement_trace"]["drafted"] is True
    assert "body" not in str(buyer["state_json"])
    operator = client.get(f"{_BASE}/by-trace/{trace_id}/all/operator-view").json()["cases"][0]
    assert operator["state_json"]["draft"]["body"]

    unauthenticated = TestClient(app).get(f"{_BASE}/by-trace/{trace_id}/all/operator-view")
    assert unauthenticated.status_code in (401, 403)


def test_by_trace_404_when_no_case():
    assert client.get(f"{_BASE}/by-trace/no-such-trace-xyz").status_code == 404


def test_closed_loop_trace_survives_confirmation_and_rfq_redraft(monkeypatch):
    """One immutable recommendation trace must own the initial and amended sourcing history."""
    monkeypatch.setenv("FULFILLMENT_AUTO_DRAFT_ON_COMMIT", "1")
    from src.app.models.db import db_session
    from src.app.services.supplier_catalog import ensure_supplier_coverage
    with db_session() as db:
        ensure_supplier_coverage(db)

    suffix = uuid.uuid4().hex[:10]
    trace_id = f"T-CLOSED-{suffix}"
    order_id = f"O-CLOSED-{suffix}"
    uid = f"buyer-{suffix}"
    requirements = {"needed_by": "2026-08-20", "use_case": "game development",
                    "ship_to": "Sydney NSW 2000"}

    first = client.post(f"{_BASE}/confirm-cart", json={
        "uid": uid, "order_id": order_id, "trace_id": trace_id, "requirements": requirements,
        "lines": [{"item_ref": "GAM-0002", "requested_qty": 20, "in_stock": 15, "source_qty": 5}],
    })
    assert first.status_code == 200, first.text
    first_case = first.json()["cases"][0]["case_id"]
    first_state = client.get(f"{_BASE}/{first_case}/operator-view").json()["state_json"]
    assert first_state["availability"]["shortfall"] == 5
    assert first_state["availability"]["lines"][0]["approved_source_override"] == 5
    assert first_state["availability"]["lines"][0]["source_override_authority"] == "buyer_confirm_cart"
    committed = client.post(f"{_BASE}/{first_case}/commit", json={"uid": uid})
    assert committed.status_code == 200 and committed.json()["state"] == "QUOTE_DRAFTED", committed.text
    first_draft = client.get(f"{_BASE}/{first_case}/operator-view").json()["state_json"]["draft"]
    assert first_draft["commercial_scope"]["quantity"] == 5
    assert "Quantity: 5" in first_draft["body"]

    amended_trace_id = f"{trace_id}-amended"
    amended = client.post(f"{_BASE}/confirm-cart", json={
        "uid": uid, "order_id": order_id, "trace_id": amended_trace_id, "supersede": True,
        "lines": [{"item_ref": "GAM-0002", "requested_qty": 15, "in_stock": 12, "source_qty": 3}],
    })
    assert amended.status_code == 200, amended.text
    assert amended.json()["status"] == "superseded"
    second_case = amended.json()["created"]["cases"][0]["case_id"]
    assert second_case != first_case
    redrafted = client.post(f"{_BASE}/{second_case}/commit", json={"uid": uid})
    assert redrafted.status_code == 200 and redrafted.json()["state"] == "QUOTE_DRAFTED", redrafted.text
    second_draft = client.get(f"{_BASE}/{second_case}/operator-view").json()["state_json"]["draft"]
    assert second_draft["commercial_scope"]["quantity"] == 3
    assert "Quantity: 3" in second_draft["body"]
    assert second_draft["content_hash"] != first_draft["content_hash"]

    active = client.get(f"{_BASE}/by-trace/{amended_trace_id}/all/operator-view")
    assert active.status_code == 200
    assert active.json()["trace_id"] == amended_trace_id
    assert [case["case_id"] for case in active.json()["cases"]] == [second_case]
    projected = active.json()["amendment_history"]
    assert projected["case_count"] == 2
    assert set(projected["trace_ids"]) == {trace_id, amended_trace_id}
    assert projected["draft_diff"]["quantity"] == {"from": 5, "to": 3}
    old_trace = client.get(f"{_BASE}/by-trace/{trace_id}/all/operator-view")
    assert old_trace.status_code == 200
    assert old_trace.json()["cases"] == []
    history = client.get(f"{_BASE}/by-order/{order_id}").json()
    assert history["case_count"] == 2
    assert history["draft_diff"]["changed"] is True
    assert history["draft_diff"]["quantity"] == {"from": 5, "to": 3}


@pytest.mark.slow
def test_market_refresh_and_state_run_the_real_pipeline():
    # operator-triggered REAL pipeline (default tenant) — returns 200 + a LIVE state (counts may be 0
    # when the source tables are empty; the point is the wiring + tenant label).
    r = client.post("/api/v1/fulfillment/market/refresh")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "refreshed" in body and body["state"]["label"] == "LIVE"
    s = client.get("/api/v1/fulfillment/market/state")
    assert s.status_code == 200 and s.json()["label"] == "LIVE"


def test_market_refresh_and_state_follow_request_tenant(monkeypatch):
    from src.app.services import market_pipeline

    seen = []

    def fake_run(_db, *, tenant_id, **kwargs):
        seen.append(("run", tenant_id))
        return {"ingested": 0, "findings": 0, "persisted": 0}

    def fake_state(_db, *, tenant_id, **kwargs):
        seen.append(("state", tenant_id))
        return {"signals": 0, "active_findings": 0, "findings": [], "label": "LIVE"}

    monkeypatch.setattr(market_pipeline, "run_pipeline", fake_run)
    monkeypatch.setattr(market_pipeline, "state", fake_state)
    headers = {"X-Tenant-Id": "tenant-market-a"}
    refreshed = client.post("/api/v1/fulfillment/market/refresh", headers=headers)
    state = client.get("/api/v1/fulfillment/market/state", headers=headers)

    assert refreshed.status_code == 200
    assert refreshed.json()["tenant_id"] == "tenant-market-a"
    assert state.status_code == 200
    assert state.json()["tenant_id"] == "tenant-market-a"
    assert seen == [
        ("run", "tenant-market-a"),
        ("state", "tenant-market-a"),
        ("state", "tenant-market-a"),
    ]


def test_edit_draft_and_asof_routes_wired():
    cid = _open()
    # edit-draft from NEW has no draft → 409 (route exists + guards), not a 404 unrouted
    r = client.post(f"{_BASE}/{cid}/edit-draft", json={"body": "x"})
    assert r.status_code == 409
    # as-of before the case existed → no version → 404
    a = client.get(f"{_BASE}/{cid}/as-of", params={"t": "2000-01-01 00:00:00"})
    assert a.status_code == 404


def test_experiment_console_promote_observe_revert():
    # operator levers over a uniquely scoped, sealed experiment policy
    experiment_id = f"ranking-console-{uuid.uuid4()}"
    policy = {
        "experiment_id": experiment_id,
        "baseline": {"variant": "control"},
        "eligibility": {"surface": "recommendation"},
        "min_samples": 30,
        "min_window_seconds": 86400,
        "rollback_threshold_pct": 2.0,
        "guardrails": {"margin": "non_decreasing"},
        "terminal_policy": {
            "allowed": ["keep", "scale", "revise", "revert"],
        },
    }
    p = client.post(
        "/api/v1/fulfillment/market/experiment/promote",
        json=policy,
    )
    assert p.status_code == 200 and p.json()["live"] is True
    s = client.get(
        "/api/v1/fulfillment/market/experiment/state",
        params={"experiment_id": experiment_id},
    )
    assert s.status_code == 200 and s.json()["live"] is True
    rev = client.post(
        "/api/v1/fulfillment/market/experiment/revert",
        json={"experiment_id": experiment_id},
    )
    assert rev.status_code == 200 and rev.json()["live"] is False


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
