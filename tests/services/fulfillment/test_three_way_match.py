"""Three-way match — the AP control: PO = goods-receipt = invoice before payment."""
from __future__ import annotations

from src.app.services.fulfillment import domain as d
from src.app.services.fulfillment.domain import Actor, ActorType as A, FulfillmentState as S
from src.app.services.fulfillment.three_way_match import match, match_for_case

_PO = {"quantity": 10, "total_amount_cents": 100000}      # 10 units, $1,000


def test_clean_match_passes():
    r = match(_PO, {"quantity": 10}, {"quantity": 10, "amount_cents": 100000})
    assert r["matched"] is True and r["mismatches"] == []


def test_missing_documents_block():
    assert "missing_goods_receipt" in match(_PO, None, {"quantity": 10, "amount_cents": 100000})["mismatches"]
    assert "missing_invoice" in match(_PO, {"quantity": 10}, None)["mismatches"]


def test_quantity_mismatch_blocks():
    r = match(_PO, {"quantity": 9}, {"quantity": 10, "amount_cents": 100000})  # received 9, ordered 10
    assert r["matched"] is False and any("qty_po_vs_receipt" in m for m in r["mismatches"])


def test_amount_mismatch_beyond_tolerance_blocks():
    r = match(_PO, {"quantity": 10}, {"quantity": 10, "amount_cents": 130000})  # invoice $1,300 vs PO $1,000
    assert r["matched"] is False and any("amount_po_vs_invoice" in m for m in r["mismatches"])


def test_amount_within_tolerance_passes():
    r = match(_PO, {"quantity": 10}, {"quantity": 10, "amount_cents": 101500})  # +1.5% < 2% default
    assert r["matched"] is True


def test_match_for_case_reads_state_json():
    sj = {"purchase_order": _PO, "goods_receipt": {"quantity": 10},
          "invoice": {"quantity": 10, "amount_cents": 100000}}
    assert match_for_case(sj)["matched"] is True


def test_receipt_and_invoice_are_self_loops_post_po():
    # the documents are recorded WITHOUT changing state (READY_TO_SHIP self-loop), by SYSTEM or operator.
    for ev in ("goods_receipt_recorded", "invoice_recorded"):
        assert d.next_state(S.READY_TO_SHIP, ev, Actor(A.SYSTEM, "edi")) == S.READY_TO_SHIP
        assert d.next_state(S.READY_TO_SHIP, ev, Actor(A.HUMAN_OPERATOR, "ap")) == S.READY_TO_SHIP
        # the buyer/agent may not record receipt/invoice (AP-side documents)
        ok, _ = d.can_fire(S.READY_TO_SHIP, ev, Actor(A.BUYER, "u1"))
        assert ok is False
