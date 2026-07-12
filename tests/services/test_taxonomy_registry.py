"""T1 taxonomy registry: pinned-release integrity, deterministic lookups, the write-side
clamp, and the tri-state is_sold() semantics that reground off-catalog honesty."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.services.taxonomy_registry import (
    PINNED_RELEASE,
    add_sold_node,
    ancestors,
    approve_classification,
    children,
    get_node,
    is_sold,
    materialize_sold_taxonomy,
    node_count,
    parent_handle,
    primary_sold_node,
    search_nodes,
    sold_nodes,
    upsert_classification,
)


@pytest.fixture()
def db():
    s = sessionmaker(bind=create_engine("sqlite://"))()
    yield s
    s.close()


# ── primary_sold_node: the M3-C1 workload reroute target ──────────────────────

def test_primary_sold_node_is_most_classified(db):
    add_sold_node(db, node_handle="el-6-6")       # Laptops
    add_sold_node(db, node_handle="el-9-3")       # (some accessory)
    # 3 laptops, 1 accessory → Laptops dominates
    for sku in ("A", "B", "C"):
        upsert_classification(db, sku=sku, node_handle="el-6-6", source="t", status="approved")
    upsert_classification(db, sku="D", node_handle="el-9-3", source="t", status="approved")
    db.commit()
    assert primary_sold_node(db) == "el-6-6"


def test_primary_sold_node_counts_subtree_under_a_coarse_grant(db):
    add_sold_node(db, node_handle="el-6-6")        # coarse grant
    # per-leaf classifications SIT UNDER the grant → counted toward it
    upsert_classification(db, sku="A", node_handle="el-6-6-1", source="t", status="approved")
    upsert_classification(db, sku="B", node_handle="el-6-6-2", source="t", status="approved")
    db.commit()
    assert primary_sold_node(db) == "el-6-6"


def test_primary_sold_node_none_when_ungrounded(db):
    assert primary_sold_node(db) is None           # no sold set → no reroute target


# ── pinned release integrity (drift tests — rerun on every release upgrade) ──

def test_release_pinned_and_loaded():
    assert PINNED_RELEASE == "2026-05"
    assert node_count() == 14606


def test_hierarchy_encoded_in_handles():
    """Ancestry is handle-prefix string math — verify the assumption holds for the WHOLE
    vendored file (every non-root node's parent handle must exist)."""
    from src.app.services.taxonomy_registry import _nodes
    nodes = _nodes()
    orphans = [h for h in nodes if (p := parent_handle(h)) is not None and p not in nodes]
    assert orphans == []


def test_known_nodes_and_paths():
    lap = get_node("el-6-6")
    assert lap and lap.name == "Laptops" and lap.full_path == "Electronics > Computers > Laptops"
    srv = get_node("el-6-2")
    assert srv and srv.name == "Computer Servers"
    assert get_node("gid://shopify/TaxonomyCategory/el-6-6").handle == "el-6-6"  # gid form works
    assert get_node("no-such-node") is None


def test_ancestors_and_children():
    chain = [n.handle for n in ancestors("el-6-6")]
    assert chain == ["el-6", "el"]
    kids = {n.handle for n in children("el-6")}
    assert "el-6-6" in kids and "el-6-2" in kids


def test_search_ranks_exact_name_first():
    got = search_nodes("laptops", limit=5)
    assert got and got[0].handle == "el-6-6"
    assert search_nodes("") == []


# ── write-side clamp ──────────────────────────────────────────────────────────

def test_classification_clamped_to_release(db):
    assert not upsert_classification(db, sku="LAP-1", node_handle="invented-node-99")
    assert upsert_classification(db, sku="LAP-1", node_handle="el-6-6", source="test", confidence=0.9)


def test_add_sold_node_clamped(db):
    assert not add_sold_node(db, node_handle="forklifts-9-9")
    assert add_sold_node(db, node_handle="el-6-6", source="bootstrap")


# ── is_sold tri-state semantics ───────────────────────────────────────────────

def test_ungrounded_tenant_is_none_never_false(db):
    """No sold set bootstrapped -> None (cannot refuse). The ungrounded-router lesson."""
    assert sold_nodes(db) is None
    assert is_sold(db, "el-6-6") is None


def test_unknown_handle_is_none(db):
    add_sold_node(db, node_handle="el-6-6")
    assert is_sold(db, "not-a-real-handle") is None


def test_subtree_sold_ancestors_not_implied(db):
    add_sold_node(db, node_handle="el-6-6")  # merchant sells Laptops
    assert is_sold(db, "el-6-6") is True
    assert is_sold(db, "el-6-2") is False    # Computer Servers: sibling — NOT sold (the A100 case)
    assert is_sold(db, "el-6") is False      # parent Computers not implied
    assert is_sold(db, "el") is False        # vertical root not implied
    assert is_sold(db, "fr-4-3-11") is False # Furniture: definitely not sold (forklift-class case)


def test_descendants_inherit_sold(db):
    add_sold_node(db, node_handle="el-6")    # merchant sells Computers
    assert is_sold(db, "el-6-6") is True     # Laptops inherit
    assert is_sold(db, "el-6-2") is True     # so do Computer Servers — subtree semantics are honest
    assert is_sold(db, "el-7") is False      # Electronics Accessories: sibling, not covered


def test_sells_within_is_the_refusal_gate(db):
    """Per-product classification grants LEAVES; a parent-category query must not refuse."""
    from src.app.services.taxonomy_registry import sells_within
    add_sold_node(db, node_handle="hb-1-9-6-9-5")   # store sells only Vitamin D
    assert is_sold(db, "hb-1-9-6") is False          # strict: parent not fully covered
    assert sells_within(db, "hb-1-9-6") is True      # refusal gate: do NOT refuse vitamins
    assert sells_within(db, "hb-1-9-6-9-5") is True  # the leaf itself
    assert sells_within(db, "el-6-2") is False       # servers: no overlap → refusable
    assert sells_within(db, "not-a-node") is None    # unknown → ungrounded, never refuse


def test_sells_within_ungrounded_is_none(db):
    from src.app.services.taxonomy_registry import sells_within
    assert sells_within(db, "el-6-6") is None


def test_approval_materializes_sold_set(db):
    upsert_classification(db, sku="LAP-1", node_handle="el-6-6", source="model", confidence=0.92)
    upsert_classification(db, sku="AUD-1", node_handle="el-13", source="model", confidence=0.88)
    assert materialize_sold_taxonomy(db, commit=False)["added"] == 0  # nothing approved yet
    approve_classification(db, sku="LAP-1", approved_by="merchant@demo")
    assert materialize_sold_taxonomy(db, commit=False)["added"] == 1
    assert is_sold(db, "el-6-6") is True
    assert is_sold(db, "el-13") is False     # proposed-but-unapproved never grounds a sale


def test_materialize_is_reconciliation_with_retirement(db):
    """Reclassifying a product must RETIRE its old node from the sold set (GPT-5.6 #2) —
    while manual/merchant grants survive untouched."""
    upsert_classification(db, sku="PHM-1", node_handle="hb-3-12-14-13", source="model", confidence=0.95)
    approve_classification(db, sku="PHM-1", approved_by="m@demo")
    add_sold_node(db, node_handle="el-6-11-2", source="merchant_declaration")  # manual grant
    r = materialize_sold_taxonomy(db, commit=False)
    assert r["added"] == 1 and is_sold(db, "hb-3-12-14-13") is True
    # human corrects the classification to the right node
    upsert_classification(db, sku="PHM-1", node_handle="hb-1-16-1", source="human_correction",
                          confidence=1.0, status="proposed")
    approve_classification(db, sku="PHM-1", approved_by="m@demo")
    r = materialize_sold_taxonomy(db, commit=False)
    assert r["retired"] == 1 and r["added"] == 1
    assert is_sold(db, "hb-3-12-14-13") is False   # stale grant GONE
    assert is_sold(db, "hb-1-16-1") is True         # corrected node sold
    assert is_sold(db, "el-6-11-2") is True         # manual declaration PRESERVED


def test_alembic_ddl_matches_service_ddl():
    """The migration's DDL must stay textually identical to the runtime ensure_tables DDL
    (repo convention, same as catalog_entities) — drift here means prod and dev schemas fork."""
    import importlib.util
    from pathlib import Path
    from src.app.services import taxonomy_registry as tr
    mig_path = Path(tr.__file__).resolve().parents[3] / "alembic" / "versions" / "20260711_taxonomy_grounding.py"
    spec = importlib.util.spec_from_file_location("mig", mig_path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    service_ddl = [tr._CLASSIFICATION_DDL.strip(), tr._SOLD_DDL.strip(), *[i.strip() for i in tr._INDEXES]]
    migration_ddl = [s.strip() for s in mig.TABLE_STATEMENTS]
    assert migration_ddl == service_ddl


def test_grounding_status_distinguishes_empty_from_error(db):
    from src.app.services.taxonomy_registry import grounding_status
    assert grounding_status(db) == "empty"           # tables exist, nothing granted
    add_sold_node(db, node_handle="el-6-6")
    assert grounding_status(db) == "grounded"
    assert grounding_status(None) == "error"         # infra failure is NOT 'ungrounded tenant'
