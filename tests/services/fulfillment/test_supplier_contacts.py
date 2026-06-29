"""Supplier-contact candidates agent — ranked, confidence-scored, provenance-tagged, allowlist-only.
Integration-style against the app DB (the resolvers open their own sessions), seeded like the draft tests."""
from __future__ import annotations

from src.app.models.db import db_session
from src.app.services import supplier_catalog
from src.app.services.fulfillment.supplier_contacts import _confidence, supplier_contact_candidates
from src.app.services.inventory_agent import InventoryAgent
from src.app.services.supplier_catalog import seed_demo_supplier_history, seed_demo_vendor_contacts


def _seed():
    with db_session() as db:
        supplier_catalog.seed_demo(db, skus=["LAP-021"])
    seed_demo_vendor_contacts()
    seed_demo_supplier_history()


def test_confidence_weights_verified_contact_highest():
    with_contact = _confidence(has_contact=True, on_time=0.0, reliability=0.0, has_history=False)
    without = _confidence(has_contact=False, on_time=1.0, reliability=1.0, has_history=True)
    assert with_contact == 0.4
    assert without == 0.6  # reliability signals still count, but no contact caps it short of full trust
    assert _confidence(has_contact=True, on_time=1.0, reliability=1.0, has_history=True) == 1.0


def test_rank_suppliers_returns_scored_topn():
    _seed()
    ranked = InventoryAgent()._rank_suppliers("LAP-021", top_n=3)
    # ranking invariant: ≥1 approved supplier, scored descending. (Which suppliers cover the SKU depends on
    # the profile's supplier_routing_rules, so don't pin the exact set — base vs routed differ.)
    assert len(ranked) >= 1 and all(r.get("id") and r.get("score") is not None for r in ranked)
    assert all(ranked[i]["score"] >= ranked[i + 1]["score"] for i in range(len(ranked) - 1))


def test_candidates_resolve_verified_allowlist_contacts():
    _seed()
    with db_session() as db:
        cands = supplier_contact_candidates(db, item_ref="LAP-021")
    assert len(cands) >= 1                       # at least the routed approved supplier
    top = cands[0]
    assert top["recommended"] is True
    assert top["contact_email"].endswith("@" + top["domain"])  # contact ON the resolved allowlist domain
    assert top["provenance"]["domain"] == "supplier_allowlist"


def test_candidates_empty_for_unknown_sku():
    _seed()
    with db_session() as db:
        assert supplier_contact_candidates(db, item_ref="NO-SUCH-SKU") == []
        assert supplier_contact_candidates(db, item_ref="") == []
