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


# ── resolve_pr: the R1 fix — amendments reuse, new carts get a distinct PR ─────
def test_amendments_reuse_the_same_pr_no_churn():
    s0 = pr.resolve_pr(None, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:00:00", nonce="t1")
    s1 = pr.resolve_pr(s0, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:01:00", nonce="t2")
    s2 = pr.resolve_pr(s1, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:02:00", nonce="t3")
    assert s0["pr_id"] == s1["pr_id"] == s2["pr_id"]      # three amendment turns → ONE PR (no churn)
    assert s2["last_activity"] == "2026-06-30 09:02:00"   # activity advances


def test_idle_past_ttl_rotates_to_a_new_pr():
    s0 = pr.resolve_pr(None, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:00:00", nonce="t1")
    # next sourcing 25h later = a new cart → DISTINCT PR (no cross-order capture of a stale cart)
    s1 = pr.resolve_pr(s0, tenant_id="default", buyer_key="u1", now_iso="2026-07-01 10:00:00", nonce="t9")
    assert s1["pr_id"] != s0["pr_id"]


def test_explicit_new_and_finalize_rotate():
    s0 = pr.resolve_pr(None, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:00:00", nonce="t1")
    # explicit "start a new order"
    s_new = pr.resolve_pr(s0, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:05:00",
                          nonce="t2", explicit_new=True)
    assert s_new["pr_id"] != s0["pr_id"]
    # finalize (order placed) → the NEXT resolve rotates
    s_fin = pr.mark_finalized(s0)
    s_after = pr.resolve_pr(s_fin, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:06:00", nonce="t3")
    assert s_after["pr_id"] != s0["pr_id"]


def test_two_buyers_never_share_a_pr():
    a = pr.resolve_pr(None, tenant_id="default", buyer_key="u1", now_iso="2026-06-30 09:00:00", nonce="t")
    b = pr.resolve_pr(None, tenant_id="default", buyer_key="u2", now_iso="2026-06-30 09:00:00", nonce="t")
    assert a["pr_id"] != b["pr_id"]
