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
    r = _requests.post(f"{BACKEND}{path}", headers=_HDR, timeout=30, **kw)
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
    assert _post(f"{_FC}/{cid}/commit", json={"uid": "rec-buyer"})["state"] == "COMMITTED"

    # agent drafts → request approval (needs a seeded approved supplier; otherwise NO_APPROVED_SUPPLIER)
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


@pytest.mark.skipif(not _have_pw, reason="playwright unavailable")
def test_buyer_storefront_renders_procurement_check():
    """Browser half: the buyer sees the procurement check after a bulk request (UI smoke)."""
    if not _up():
        pytest.skip("stack not reachable")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        page.goto(FRONTEND, timeout=20000)
        page.get_by_placeholder("Type your message...").fill(
            "I need 10 laptops for a design team under $1500 each within two weeks")
        page.keyboard.press("Enter")
        # the fulfilment block renders when the response carries a case (FULFILLMENT_CASES_ENABLED)
        page.wait_for_selector("[data-testid='fulfilment-options'], [data-testid='product-grid']", timeout=20000)
        browser.close()
