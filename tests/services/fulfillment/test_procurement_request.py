"""Procurement Request identity — stable anchor, naming hierarchy, rotation policy."""
from __future__ import annotations

from src.app.services.fulfillment import procurement_request as pr


def test_mint_is_stable_for_same_inputs_distinct_for_new_cart():
    a = pr.mint_pr_id(tenant_id="default", buyer_key="u1", opened_at_iso="2026-06-30 09:00:00", nonce="cart-A")
    a2 = pr.mint_pr_id(tenant_id="default", buyer_key="u1", opened_at_iso="2026-06-30 09:00:00", nonce="cart-A")
    b = pr.mint_pr_id(tenant_id="default", buyer_key="u1", opened_at_iso="2026-06-30 09:00:00", nonce="cart-B")
    assert a == a2          # idempotent re-mint of the SAME cart → same PR (no churn)
    assert a != b           # a genuinely new cart (new nonce) → distinct PR (no cross-order collision)
    assert pr.is_pr_id(a) and a.startswith("PR-default-20260630-")


def test_pr_id_parses_for_audit():
    p = pr.mint_pr_id(tenant_id="acme", buyer_key="u9", opened_at_iso="2026-12-01T10:00:00", nonce="n")
    parsed = pr.parse_pr_id(p)
    assert parsed["tenant"] == "acme" and parsed["date"] == "20261201" and len(parsed["short"]) >= 8
    assert pr.parse_pr_id("not-a-pr") == {}


def test_naming_hierarchy_is_stable_and_nested():
    p = "PR-default-20260630-abcdef1234"
    case = pr.case_ref(p, "SUP-CREATOR")
    po = pr.po_ref(p, 1)
    assert case == "CASE-PR-default-20260630-abcdef1234-sup-creator"
    assert po == "PO-PR-default-20260630-abcdef1234-1"
    assert pr.goods_receipt_ref(po) == "GR-PO-PR-default-20260630-abcdef1234-1"
    assert pr.invoice_ref(po) == "INV-PO-PR-default-20260630-abcdef1234-1"


def test_amendment_sequence_is_append_only():
    assert pr.next_amendment_seq(None) == 1
    assert pr.next_amendment_seq(0) == 1
    assert pr.next_amendment_seq(3) == 4
    assert pr.amendment_label("PR-x", 2) == "PR-x#v2"


def test_rotation_keeps_amendments_stable_rotates_on_lifecycle():
    # the whole point: amending an active cart does NOT rotate (stable identity across mind-changes)
    assert pr.should_rotate() is False
    assert pr.should_rotate(idle_seconds=60, idle_ttl_seconds=86400) is False
    # rotate only on a real lifecycle event
    assert pr.should_rotate(explicit_new=True) is True            # buyer started a new order
    assert pr.should_rotate(finalized=True) is True               # prior order was placed
    assert pr.should_rotate(idle_seconds=90000, idle_ttl_seconds=86400) is True  # stale cart safety net


def test_retention_window_is_compliance_grade():
    assert pr.RETENTION_WINDOW_DAYS >= 365 * 7   # financial/procurement record retention
