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
