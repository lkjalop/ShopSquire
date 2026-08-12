from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.orm import Base
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.case_catalog_candidates import build_case_catalog_candidate_set
from src.app.services.catalog_evidence_seed import ingest_reviewed_configurations


def _database():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return engine


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
    assert skus == {"SCORP-126982", "SCORP-125638", "JW-822962"}
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
    assert len(candidate_set.configuration_ids) == 3


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
