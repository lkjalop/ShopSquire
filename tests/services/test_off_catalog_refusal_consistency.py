"""Characterize refusal safety across the legacy denylist and V2 sold-taxonomy allowlist."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _db_with_demo_sold_nodes():
    from scripts.bootstrap_sold_taxonomy import DEMO_SOLD_NODES
    from src.app.services.taxonomy_registry import add_sold_node

    db = sessionmaker(bind=create_engine("sqlite+pysqlite:///:memory:", future=True))()
    for handle in DEMO_SOLD_NODES.values():
        assert add_sold_node(db, node_handle=handle, source="test", approved_by="test")
    db.commit()
    return db


def test_no_sold_category_is_denylisted_by_legacy_off_catalog():
    from src.app.services.off_catalog_gate import off_catalog_check
    from src.app.services.taxonomy_registry import get_node, sold_nodes

    db = _db_with_demo_sold_nodes()
    try:
        sold = sold_nodes(db, tenant_id="default")
    finally:
        db.close()
    assert sold

    contradictions = []
    for handle in sold:
        node = get_node(handle)
        if node is None:
            continue
        leaf = node.full_path.split(">")[-1].strip() if node.full_path else node.name
        for probe in {node.name, leaf}:
            if probe and off_catalog_check(probe) is not None:
                contradictions.append((handle, node.name, probe))
                break
    assert not contradictions, (
        "legacy off_catalog denylist would refuse categories in the approved demo sold set: "
        f"{contradictions[:10]}"
    )


def test_representative_sold_categories_are_not_denylisted():
    from src.app.services.off_catalog_gate import off_catalog_check

    sold_categories = [
        "laptops", "gaming laptop", "monitors", "gaming monitor", "tablets", "graphics tablet",
        "drawing tablet", "keyboards", "mice", "gaming headset", "wifi router", "hard drive",
        "portable ssd", "printer", "backpack",
    ]
    denylisted = [category for category in sold_categories if off_catalog_check(category) is not None]
    assert not denylisted


def test_demo_bootstrap_uses_valid_cross_vertical_taxonomy_namespaces():
    from scripts.bootstrap_sold_taxonomy import DEMO_SOLD_NODES
    from src.app.services.taxonomy_registry import get_node

    assert {handle.split("-", 1)[0] for handle in DEMO_SOLD_NODES.values()} == {"aa", "el", "hb", "lb"}
    missing = {prefix: handle for prefix, handle in DEMO_SOLD_NODES.items() if get_node(handle) is None}
    assert not missing


def test_legacy_denylist_still_refuses_datacenter_gpu():
    from src.app.services.off_catalog_gate import off_catalog_check

    for query in ("an A100 datacenter GPU server", "rack-mount server with H100", "a DGX box"):
        assert off_catalog_check(query) is not None


def test_forklifts_documents_the_denylist_vs_allowlist_gap():
    from src.app.services.off_catalog_gate import off_catalog_check

    assert off_catalog_check("do you sell forklifts?") is None
