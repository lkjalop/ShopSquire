from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.app.models.orm import (
    Base, Product, ProductAvailabilityObservation, ProductConfiguration,
    ProductEvidenceObservation,
)
from src.app.services.catalog_evidence_seed import ingest_reviewed_configurations


def test_reviewed_fixture_preserves_identity_conflicts_and_form_factor_specific_vram():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = ingest_reviewed_configurations(db)
        second = ingest_reviewed_configurations(db)
        assert first == second
        configs = db.execute(select(ProductConfiguration)).scalars().all()
        assert len(configs) == 5
        assert all(row.mpn and row.configuration_hash and row.product_id for row in configs)
        products = db.execute(select(Product)).scalars().all()
        assert {row.sku for row in products} == {row.sku for row in configs}

        titan = next(row for row in configs if row.sku == "SCORP-126982")
        zephyr = next(row for row in configs if row.sku == "JW-818845")
        assert (titan.form_factor, titan.gpu_vram_gb) == ("laptop", 24)
        assert (zephyr.form_factor, zephyr.gpu_vram_gb) == ("desktop_tower", 32)

        conflicts = db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.conflict_group == "zephyr-cpu",
        )).scalars().all()
        assert {row.value_json["value"] for row in conflicts} == {
            "Ryzen 7 9800X3D", "Ryzen 7 7800X3D",
        }
        assert all(row.evidence_status == "conflicted" for row in conflicts)

        built = db.execute(select(ProductAvailabilityObservation).where(
            ProductAvailabilityObservation.configuration_id == zephyr.id,
        )).scalar_one()
        assert (built.status, built.lead_time_min_days, built.lead_time_max_days) == (
            "built_to_order", 6, 8,
        )
