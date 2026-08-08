from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.models.orm import Base
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.catalog_evidence_seed import ingest_reviewed_configurations


def test_accepted_claims_build_shared_conditional_and_budget_shelves_without_false_qualification():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        claims = [
            {"claim_id": "ram", "attribute": "ram_gb", "operator": ">=", "value": 32, "requirement_class": "minimum"},
            {"claim_id": "storage", "attribute": "storage_gb", "operator": ">=", "value": 1000, "requirement_class": "minimum"},
            {"claim_id": "gpu", "attribute": "gpu_class", "operator": "conditional", "value": "consumer_geforce", "requirement_class": "recommended", "condition": "if local 3D runs"},
        ]
        projection = project_accepted_catalog(
            db, accepted_claims=claims, budget_cents=600_000,
            desired_outcome="ambiguous local workload",
            hypothesis_labels={"local_vm": "Local virtual machines"},
        )

    shelf_ids = {shelf.shelf_id for shelf in projection.shelves}
    assert "shared:within_budget" in shelf_ids
    assert "shared:stretch" in shelf_ids
    assert "conditional_scope:within_budget" in shelf_ids
    assert "architecture:desktop_workstation:within_budget" in shelf_ids
    assert "architecture:mobile_workstation:stretch" in shelf_ids
    assert "local_vm:within_budget" in shelf_ids
    assert all(
        product.fit_status == "conditional"
        for shelf in projection.shelves for product in shelf.initial + shelf.next_page
    )
    assert all(len(shelf.initial) <= 3 and len(shelf.next_page) <= 5 for shelf in projection.shelves)


def test_hypothesis_shelf_uses_only_claims_bound_to_that_research_scope():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        shared = {
            "claim_id": "shared-os", "attribute": "operating_system",
            "operator": "one_of", "value": ["Windows 11 Pro"],
            "requirement_class": "minimum", "authority_status": "verified_official",
        }
        point_cloud = {
            "claim_id": "autodesk-vram", "source_id": "autodesk",
            "attribute": "gpu_vram_gb", "operator": ">=", "value": 12,
            "requirement_class": "target", "authority_status": "verified_official",
            "condition": "large point clouds",
        }
        projection = project_accepted_catalog(
            db, accepted_claims=[shared, point_cloud],
            hypothesis_labels={"point_cloud": "Large point-cloud CAD"},
            hypothesis_claims={"point_cloud": [point_cloud]},
        )

    shared_shelf = next(row for row in projection.shelves if row.scope_id == "shared")
    point_shelf = next(row for row in projection.shelves if row.scope_id == "point_cloud")
    assert all("gpu vram gb" not in row.unknowns for row in shared_shelf.initial)
    assert any(
        "gpu vram gb" in [*row.meets, *row.unknowns, *row.misses]
        for row in point_shelf.initial
    )


def test_exact_observations_supply_claim_refs_independent_freshness_and_location_stock():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(
            db,
            accepted_claims=[{
                "claim_id": "official-ram",
                "attribute": "ram_gb",
                "operator": ">=",
                "value": 64,
                "requirement_class": "minimum",
                "authority_status": "verified_official",
            }],
            desired_outcome="named exact workload",
            now=datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
        )

    shared = next(row for row in projection.shelves if row.scope_id == "shared")
    titan = next(row for row in [*shared.initial, *shared.next_page] if row.product.sku == "SCORP-126982")
    assert titan.fit_status == "qualified"
    assert titan.requirement_claim_ids == ["official-ram"]
    assert titan.capability_claim_ids
    assert titan.evidence_freshness.specification == "fresh"
    assert titan.evidence_freshness.price == "fresh"
    assert titan.evidence_freshness.availability == "fresh"
    assert {row.location_id for row in titan.availability} == {
        "australia_delivery", "dandenong",
    }
    assert all(row.freshness_status == "fresh" for row in titan.availability)


def test_conflicting_exact_configuration_observations_remain_contested():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(
            db,
            accepted_claims=[{
                "claim_id": "cpu-model",
                "attribute": "cpu_model",
                "operator": "=",
                "value": "Ryzen 7 9800X3D",
                "requirement_class": "minimum",
                "authority_status": "verified_official",
            }],
            now=datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
        )

    shared = next(row for row in projection.shelves if row.scope_id == "shared")
    zephyr = next(row for row in [*shared.initial, *shared.next_page] if row.product.sku == "JW-818845")
    assert zephyr.fit_status == "conditional"
    assert "cpu model" in zephyr.unknowns
    assert "cpu model" not in zephyr.misses
    assert len(zephyr.capability_claim_ids) == 2


def test_product_clocks_age_independently_and_workstation_identity_is_preserved():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(
            db, accepted_claims=[],
            now=datetime(2026, 8, 10, 1, tzinfo=timezone.utc),
        )

    products = {
        product.product.sku: product
        for shelf in projection.shelves
        for product in [*shelf.initial, *shelf.next_page]
    }
    zbook = products["JW-822962"]
    z2 = products["SCORP-C07NXPT"]
    assert zbook.product.form_factor == "mobile_workstation"
    assert z2.product.form_factor == "fixed_workstation"
    assert zbook.evidence_freshness.specification == "fresh"
    assert zbook.evidence_freshness.price == "stale"
    assert zbook.evidence_freshness.availability == "stale"
