"""Step 8 — the auditable-procurement recording path (run against a LIVE stack).

Drives the full governed journey end-to-end so it can be recorded:
  buyer bulk request → procurement check (shortfall) → buyer commits (GATE 1) → operator drafts →
  approve+send (GATE 2, hash-checked) → deterministic supplier reply → validate → options →
  buyer selects → journey/audit.

Skips cleanly when Playwright/stack/env is absent (safe in unit CI). Requires a running stack with
FULFILLMENT_CASES_ENABLED + FULFILLMENT_DEMO_ENABLED, plus seeded inventory + a trusted supplier domain.
The deterministic backend equivalent of this flow is proven in tests/services/fulfillment/* + the API
smoke test; this is the live browser/API acceptance harness (#9 shadow acceptance).

Env: BACKEND_SMOKE_URL (default :8080), SHOPSQUIRE_API_KEY, GATE_PROCUREMENT=1 to enable.
"""
from __future__ import annotations

import os

import pytest
import requests as _requests

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    _have_pw = True
except Exception:
    _have_pw = False

BACKEND = os.getenv("BACKEND_SMOKE_URL", "http://127.0.0.1:8080")
FRONTEND = os.getenv("FRONTEND_SMOKE_URL", "http://127.0.0.1:5173")
API_KEY = os.getenv("SHOPSQUIRE_API_KEY", "local-merchant-key")
_ENABLED = os.getenv("GATE_PROCUREMENT", "0").lower() in ("1", "true", "yes")
_HDR = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
_FC = f"{BACKEND}/api/v1/fulfillment/cases"


def _up() -> bool:
    try:
        return _requests.get(f"{BACKEND}/healthz", timeout=4).status_code < 500
    except Exception:
        try:
            return _requests.get(f"{BACKEND}/", timeout=4).status_code < 500
        except Exception:
            return False


pytestmark = pytest.mark.skipif(not _ENABLED, reason="set GATE_PROCUREMENT=1 against a live stack")


def _post(path, **kw):
    url = path if str(path).startswith(("http://", "https://")) else f"{BACKEND}{path}"
    r = _requests.post(url, headers=_HDR, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def test_full_governed_procurement_journey_api():
    """The complete journey through the real HTTP API on a live stack (the recording's backbone)."""
    if not _up():
        pytest.skip("backend not reachable")
    # open + assess (operator) → shortfall → buyer commits (GATE 1)
    cid = _post("/api/v1/fulfillment/cases", json={"uid": "rec-buyer", "trace_id": "REC-1"})["case_id"]
    assess = _post(f"{_FC}/{cid}/assess", json={"requested_qty": 10, "in_stock": 4, "item_ref": "LAP-021"})
    assert assess["state"] == "AWAITING_BUYER_COMMITMENT"  # no supplier contacted yet
    committed = _post(f"{_FC}/{cid}/commit", json={"uid": "rec-buyer"})
    assert committed["state"] in ("COMMITTED", "QUOTE_DRAFTED")

    # agent drafts → request approval (needs a seeded approved supplier; otherwise NO_APPROVED_SUPPLIER)
    if committed["state"] == "QUOTE_DRAFTED":
        drafted = _requests.get(f"{_FC}/{cid}/operator-view", headers=_HDR, timeout=20).json()
    else:
        drafted = _post(f"{_FC}/{cid}/draft-quote", json={"item_ref": "LAP-021", "quantity": 6})
    if drafted["state"] == "NO_APPROVED_SUPPLIER":
        pytest.skip("no approved supplier seeded — seed trusted_supplier_domains for the full path")
    assert drafted["state"] == "QUOTE_DRAFTED"
    content_hash = drafted["state_json"]["draft"]["content_hash"]
    _post(f"{_FC}/{cid}/request-approval")

    # GATE 2: approve + hash-checked send
    assert _post(f"{_FC}/{cid}/dispatch", json={"content_hash": content_hash})["state"] == "QUOTE_SENT"

    # deterministic supplier reply → parse → validate → options
    _post(f"{_FC}/{cid}/demo-reply", json={"scenario": "full_quote", "requested_qty": 6})
    assert _post(f"{_FC}/{cid}/validate-quote")["state"] == "QUOTE_VALIDATED"
    opts = _post(f"{_FC}/{cid}/options", json={})
    assert opts["state"] == "OPTIONS_READY" and opts["state_json"]["options"]

    # buyer selects → SELECTED; the journey + as-of are inspectable
    option_id = opts["state_json"]["options"][0]["option_id"]
    sel = _post(f"{_FC}/{cid}/select-option", json={"uid": "rec-buyer", "option_id": option_id})
    assert sel["state"] == "SELECTED"
    journey = _requests.get(f"{_FC}/{cid}/journey", headers=_HDR, timeout=20).json()["journey"]
    events = [e["event"] for e in journey]
    assert "external_message_sent" in events and "buyer_fulfillment_selected" in events


def test_fluid_sourcing_journey_api():
    """The FLUID procurement flow (the recent changes) through the real HTTP API on a live stack:
    confirm-cart → grouped cases → amend_required → supersede (requirements carried forward) → operator
    margin advice. Skips cleanly when the stack is down or the demo SKUs lack supplier coverage."""
    if not _up():
        pytest.skip("backend not reachable")
    _CC = f"{_FC}/confirm-cart"
    order_id = "REC-FLUID-1"

    # 1) confirm a cart's shortfall → durable grouped sourcing case(s); requirements ride along
    first = _post(_CC, json={"uid": "fluid-buyer", "order_id": order_id,
                             "requirements": {"needed_by": "2026-07-15", "use_case": "office"},
                             "lines": [{"item_ref": "LAP-021", "requested_qty": 7}]})
    if not first.get("case_count"):
        pytest.skip("LAP-021 fully in stock or no supplier coverage — seed ensure_supplier_coverage")
    assert not first.get("amend_required")
    old_case = first["cases"][0]["case_id"]

    # 2) re-confirm the SAME order with DIFFERENT lines → amend_required (not duplicated, not silent)
    amend = _post(_CC, json={"uid": "fluid-buyer", "order_id": order_id,
                             "lines": [{"item_ref": "GAM-0002", "requested_qty": 10}]})
    assert amend.get("amend_required") is True

    # 3) supersede → the old pre-send case retires, a new case is materialized
    sup = _post(_CC, json={"uid": "fluid-buyer", "order_id": order_id, "supersede": True,
                           "lines": [{"item_ref": "GAM-0002", "requested_qty": 10}]})
    assert sup.get("status") == "superseded" and old_case in (sup.get("superseded") or [])

    # the old case is terminal (SUPERSEDED) — its journey records the supersession
    j = _requests.get(f"{_FC}/{old_case}/journey", headers=_HDR, timeout=20).json()["journey"]
    assert "case_superseded" in [e["event"] for e in j]

    # 4) operator margin advice on the new active case is well-formed (verdict present; the safeguard
    #    avoids a guaranteed-loss demo). Coverage-dependent — only assert when a new case was created.
    new_cases = (sup.get("created") or {}).get("cases") or []
    if new_cases:
        adv = _requests.get(f"{_FC}/{new_cases[0]['case_id']}/margin-advice", headers=_HDR, timeout=20).json()
        assert "verdict" in adv and "available" in adv


@pytest.mark.skipif(not _have_pw, reason="playwright unavailable")
def test_buyer_storefront_renders_procurement_check():
    """Browser half: the buyer sees the procurement check after a bulk request (UI smoke)."""
    if not _up():
        pytest.skip("stack not reachable")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(FRONTEND, timeout=20000)
        page.get_by_role("button", name="Ask Me!").click()
        msg = page.get_by_placeholder("Type your message...")
        msg.wait_for(timeout=10000)
        # The AUD demo catalog's competitive-gaming floor starts above $2,000. Keep this
        # procurement smoke on an eligible product so it tests sourcing/fulfilment rendering,
        # not the separately covered below-capability-budget response.
        msg.fill("I need 20 gaming laptops for an esports lab, $3000 each within two weeks")
        msg.press("Enter")
        # The V2 advisory path renders backend fulfillment_options through BulkAlternatives;
        # committed/legacy paths use the sourcing or fulfilment cards. All are governed previews.
        page.wait_for_selector(
            "[data-testid='bulk-alternatives'], [data-testid='sourcing-intent'], "
            "[data-testid='fulfilment-options']",
            timeout=75000,
        )
        body = page.locator("body").inner_text().lower()
        assert ("needs confirmation before sourcing" in body
                or "awaiting buyer commitment" in body
                or "fulfilment options for your bulk order" in body), (
                    "expected a sourcing preview, fulfillment advisory, or procurement case")
        browser.close()
