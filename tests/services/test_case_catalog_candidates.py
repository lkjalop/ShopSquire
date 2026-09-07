from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.orm import Base
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.case_catalog_candidates import build_case_catalog_candidate_set
from src.app.services.catalog_evidence_seed import ingest_reviewed_configurations
from src.app.services.taxonomy_registry import add_sold_node


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        add_sold_node(db, node_handle="el-6-6")
        db.commit()
    return engine


def test_missing_candidate_boundary_does_not_expand_to_tenant_catalog():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(db, accepted_claims=[])
    assert all(not shelf.initial and not shelf.next_page for shelf in projection.shelves)


def test_laptop_storefront_context_bounds_shared_shelf_to_portable_configurations():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="I do CGI and do not want renders taking all night",
            tenant_id="default",
            storefront_taxonomy_handle="el-6-6",
        )
        projection = project_accepted_catalog(
            db,
            accepted_claims=[],
            candidate_configuration_ids=candidate_set.configuration_ids,
        )

    assert candidate_set.status == "eligible"
    assert candidate_set.taxonomy_source == "storefront_context"
    skus = {
        product.product.sku
        for shelf in projection.shelves if shelf.scope_id == "shared"
        for product in [*shelf.initial, *shelf.next_page]
    }
    assert len(candidate_set.configuration_ids) == 11
    assert len(skus) == 8  # stable top-three plus bounded next-five projection
    assert skus <= {
        "SCORP-126982", "SCORP-125638", "JW-822962", "JB-899169",
        "JB-816759", "JB-840466", "JB-896579", "JB-782503", "JB-840569",
        "SCORP-126560",
        "UMART-85002",
    }
    assert "SCORP-C07NXPT" not in skus
    assert "JW-818845" not in skus


def test_explicit_unsold_category_does_not_leak_laptop_candidates():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="I need an ergonomic standing desk and mesh office chair",
            tenant_id="default",
            storefront_taxonomy_handle="el-6-6",
        )
        projection = project_accepted_catalog(
            db,
            accepted_claims=[],
            candidate_configuration_ids=candidate_set.configuration_ids,
        )

    assert candidate_set.status == "out_of_category"
    assert candidate_set.taxonomy_handle == "fr-12-1-2"
    assert candidate_set.configuration_ids == []
    assert all(not shelf.initial and not shelf.next_page for shelf in projection.shelves)


def test_empty_explicit_candidate_set_never_falls_back_to_all_active_configurations():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(
            db, accepted_claims=[], candidate_configuration_ids=[],
        )

    assert all(not shelf.initial and not shelf.next_page for shelf in projection.shelves)


def test_pharmacy_category_is_outside_laptop_context():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="I need ibuprofen and a blood pressure monitor",
            tenant_id="default",
            storefront_taxonomy_handle="el-6-6",
        )

    assert candidate_set.status == "out_of_category"
    assert candidate_set.taxonomy_handle == "hb-1-4-3"
    assert candidate_set.configuration_ids == []


def test_explicit_laptop_purchase_object_outranks_workload_nouns():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="I need a laptop for drone photogrammetry and large 3D models",
            tenant_id="default",
            storefront_taxonomy_handle="el-6-6",
        )

    assert candidate_set.status == "eligible"
    assert candidate_set.taxonomy_handle == "el-6-6"
    assert len(candidate_set.configuration_ids) == 11


def test_constraint_word_does_not_override_storefront_purchase_category():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose=(
                "Should we buy 40 mobile workstations? Verify Linux support, Windows management, "
                "dock compatibility and warranty before recommending them."
            ),
            tenant_id="default",
            storefront_taxonomy_handle="el-6-6",
        )

    assert candidate_set.status == "eligible"
    assert candidate_set.taxonomy_handle == "el-6-6"
    assert candidate_set.taxonomy_source == "storefront_context"


def test_server_derives_primary_catalog_scope_without_client_handle():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="Can I run PRAGMATA under AUD 3000?",
            tenant_id="default",
            storefront_taxonomy_handle=None,
            case_id="case-1",
            case_revision=3,
        )

    assert candidate_set.status == "eligible"
    assert candidate_set.taxonomy_handle == "el-6-6"
    assert candidate_set.catalog_scope.source == "tenant_primary"
    assert candidate_set.catalog_scope.client_context_disposition == "not_supplied"
    assert candidate_set.catalog_scope.case_id == "case-1"
    assert candidate_set.catalog_scope.case_revision == 3
    assert candidate_set.configuration_ids


def test_unsold_or_forged_client_handle_is_rejected_and_tenant_scope_wins():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="Can I run this game?",
            tenant_id="default",
            storefront_taxonomy_handle="el-6-4",
        )

    assert candidate_set.status == "eligible"
    assert candidate_set.taxonomy_handle == "el-6-6"
    assert candidate_set.catalog_scope.source == "tenant_primary"
    assert candidate_set.catalog_scope.client_context_disposition == "rejected"


def test_explicit_sellable_desktop_overrides_laptop_client_context():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        add_sold_node(db, node_handle="el-6-3")
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="I need a desktop for rendering",
            tenant_id="default",
            storefront_taxonomy_handle="el-6-6",
        )

    assert candidate_set.status == "eligible"
    assert candidate_set.taxonomy_handle == "el-6-3"
    assert candidate_set.catalog_scope.source == "buyer_explicit"
    assert candidate_set.catalog_scope.client_context_disposition == "overridden"
    assert candidate_set.configuration_ids


def test_server_form_factor_maps_to_computer_servers_not_handhelds():
    from src.app.models.orm import ProductConfiguration
    from src.app.services.case_catalog_candidates import _derived_configuration_handle

    row = ProductConfiguration(
        tenant_id="default", sku="SERVER-1", product_id="product-1",
        configuration_hash="server-hash", form_factor="server",
    )
    assert _derived_configuration_handle(row) == "el-6-2"


def test_gaming_laptop_leaf_matches_coarse_laptop_configurations():
    engine = _database()
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        add_sold_node(db, node_handle="el-6-11-2")
        candidate_set = build_case_catalog_candidate_set(
            db,
            retained_purpose="I need a gaming laptop",
            tenant_id="default",
            storefront_taxonomy_handle="el-6-11-2",
        )

    assert candidate_set.status == "eligible"
    assert candidate_set.taxonomy_handle == "el-6-11-2"
    assert candidate_set.configuration_ids
