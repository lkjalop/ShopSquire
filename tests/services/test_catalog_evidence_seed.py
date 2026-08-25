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
        first = ingest_reviewed_configurations(db, inventory_profile="realistic")
        second = ingest_reviewed_configurations(db, inventory_profile="realistic")
        assert first == second
        configs = db.execute(select(ProductConfiguration)).scalars().all()
        assert len(configs) == 13
        assert sum(row.form_factor == "laptop" for row in configs) == 11
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

        exact_oem_mpns = db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.attribute_key == "manufacturer_part_number",
            ProductEvidenceObservation.source_id.in_(["MSI", "ASUS", "HP"]),
        )).scalars().all()
        assert {(row.source_id, row.value_json["value"]) for row in exact_oem_mpns} == {
            ("MSI", "Titan 18 HX A2WJ-1038AU"),
            ("MSI", "CreatorPro X18 HX A14VMG-453AU"),
            ("ASUS", "GX651AX-SR004W"),
            ("HP", "C07NXPT"),
        }
        assert {row.observed_at.date().isoformat() for row in exact_oem_mpns} == {
            "2026-08-11", "2026-08-25",
        }

        creator = next(row for row in configs if row.sku == "UMART-85002")
        creator_claims = db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.configuration_id == creator.id,
            ProductEvidenceObservation.source_id == "MSI",
        )).scalars().all()
        creator_values = {
            row.attribute_key: row.value_json["value"] for row in creator_claims
        }
        assert creator_values | {
            "ram_gb": 64,
            "gpu_family": "NVIDIA RTX 5000 Ada",
            "gpu_vram_gb": 16,
            "cpu_physical_cores": 24,
            "cpu_boost_ghz": 5.8,
            "operating_system": "Windows 11 Pro",
        } == creator_values
        assert creator.specification_observed_at.date().isoformat() == "2026-08-25"

        asus_os = db.execute(select(ProductEvidenceObservation).where(
            ProductEvidenceObservation.configuration_id
            == next(row.id for row in configs if row.sku == "SCORP-125638"),
            ProductEvidenceObservation.attribute_key == "operating_system",
        )).scalars().all()
        assert {row.value_json["value"] for row in asus_os} == {
            "Windows 11 Home", "Windows 11 Pro",
        }

        built = db.execute(select(ProductAvailabilityObservation).where(
            ProductAvailabilityObservation.configuration_id == zephyr.id,
            ProductAvailabilityObservation.source_record_id.like("https://%"),
        )).scalar_one()
        assert (built.status, built.lead_time_min_days, built.lead_time_max_days) == (
            "built_to_order", 6, 8,
        )

        inventory = {
            row.sku: sum(
                int(observation.quantity or 0)
                for observation in db.execute(select(ProductAvailabilityObservation).where(
                    ProductAvailabilityObservation.configuration_id == row.id,
                )).scalars()
            )
            for row in configs
        }
        assert inventory == {
            "SCORP-126982": 3,
            "SCORP-125638": 0,
            "JW-822962": 2,
            "UMART-85002": 0,
            "JB-899169": 12,
            "JB-816759": 7,
            "JB-840466": 0,
            "JB-896579": 5,
            "JB-782503": 0,
            "JB-840569": 4,
            "SCORP-126560": 2,
            "SCORP-C07NXPT": 0,
            "JW-818845": 0,
        }

        reviewed = next(row for row in configs if row.sku == "JB-899169")
        assert reviewed.mpn == "83S000FKAU"
        assert reviewed.retailer_sku == "899169"
        assert reviewed.specification_observed_at.date().isoformat() == "2026-08-12"
        assert reviewed.price_observed_at.date().isoformat() == "2026-08-12"
