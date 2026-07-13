"""P1-3 #1 — off-catalog refusal CONSISTENCY GATE (the canary refuse<->serve flip).

The platform has TWO refusal systems built on different truth sources that are never reconciled at
runtime, only diffed:
  • LEGACY (ships live): off_catalog_gate.off_catalog_check — a regex DENYLIST over the store
    profile's capabilities.off_catalog_classes. Refuses only what is hand-authored.
  • V2 (shadow): taxonomy_registry.sells_within — a sold-set ALLOWLIST over sold_taxonomy. Refuses
    anything whose routed node isn't in the sold set.

The day the sold set and the denylist disagree, the SAME query flips between "here are laptops" and
"we don't sell that". This makes the diff a GATE: the deterministically-checkable half (legacy
refusing a category V2 SELLS) fails CI, so a stale denylist entry can't ship into the canary. The
other half (legacy SERVING an unsold category V2 refuses — e.g. 'forklifts') is the intended
allowlist-is-stricter behavior and is documented, not asserted.

Skips cleanly when no grounded sold_taxonomy is available (mirrors the real-redis integration tests).
"""
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _db_or_skip():
    url = os.getenv("DATABASE_URL") or "sqlite:///C:/AI/ShopSquire/tmp/demo.sqlite"
    try:
        db = sessionmaker(bind=create_engine(url))()
    except Exception as exc:                       # pragma: no cover
        pytest.skip(f"no DB for consistency gate: {exc}")
    return db


def test_no_sold_category_is_denylisted_by_legacy_off_catalog():
    """THE flip guard: if a SOLD category's name matches a legacy off_catalog denylist pattern, the
    two systems flip (legacy 'we don't sell that' vs V2 'here it is'). Assert zero contradictions."""
    from src.app.services.off_catalog_gate import off_catalog_check
    from src.app.services.taxonomy_registry import get_node, sold_nodes

    db = _db_or_skip()
    try:
        sold = sold_nodes(db, tenant_id="default")
    finally:
        db.close()
    if not sold:
        pytest.skip("no grounded sold_taxonomy (empty/error) — nothing to reconcile")

    contradictions = []
    for handle in sold:
        node = get_node(handle)
        if node is None:
            continue
        # a shopper querying this sold category would use its NAME / leaf path segment; the legacy
        # denylist must not refuse it.
        leaf = node.full_path.split(">")[-1].strip() if node.full_path else node.name
        for probe in {node.name, leaf}:
            if probe and off_catalog_check(probe) is not None:
                contradictions.append((handle, node.name, probe))
                break
    assert not contradictions, (
        "legacy off_catalog denylist would REFUSE these SOLD categories that V2 SELLS "
        f"(canary refuse<->serve flip): {contradictions[:10]}")


def test_representative_sold_categories_are_not_denylisted():
    """Deterministic teeth (no DB needed): the electronics store's core SOLD categories must not be
    refused by its own off_catalog denylist. A denylist pattern broadened to catch one of these
    would flip a served category to 'we don't sell that' the moment the canary flips."""
    from src.app.services.off_catalog_gate import off_catalog_check
    sold_categories = [
        "laptops", "gaming laptop", "monitors", "gaming monitor", "tablets", "graphics tablet",
        "drawing tablet", "keyboards", "mice", "gaming headset", "wifi router", "hard drive",
        "portable ssd", "printer", "backpack",
    ]
    denylisted = [c for c in sold_categories if off_catalog_check(c) is not None]
    assert not denylisted, (
        f"legacy off_catalog denylist refuses SOLD categories (canary flip risk): {denylisted}")


def test_legacy_denylist_still_refuses_datacenter_gpu():
    """Regression: the legacy denylist must still catch the off-catalog classes it declares (the
    '$80k A100 server -> gaming laptop' fix). If this stops matching, refusal coverage regressed."""
    from src.app.services.off_catalog_gate import off_catalog_check
    for q in ("an A100 datacenter GPU server", "rack-mount server with H100", "a DGX box"):
        assert off_catalog_check(q) is not None, f"legacy denylist no longer refuses: {q!r}"


def test_forklifts_documents_the_denylist_vs_allowlist_gap():
    """DOCUMENTED divergence (not a bug to fix here): 'forklifts' is not in the hand-authored
    denylist, so LEGACY serves it (falls through to catalog search) — while V2's sold-set allowlist
    would refuse it (no sold forklift node). This is the intended 'allowlist is stricter/correct'
    behavior; the gate exists so the OTHER direction (test above) can't ship a flip. If legacy ever
    starts refusing forklifts too, the two have converged and this note can go."""
    from src.app.services.off_catalog_gate import off_catalog_check
    assert off_catalog_check("do you sell forklifts?") is None   # legacy serves (denylist gap)
