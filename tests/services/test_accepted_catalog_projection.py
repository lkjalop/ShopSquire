from datetime import datetime, timezone
import pytest
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.app.models.orm import Base, ProductConfiguration
from src.app.services.accepted_catalog_projection import project_accepted_catalog as _project_accepted_catalog
from src.app.services.catalog_evidence_seed import ingest_reviewed_configurations


@pytest.mark.parametrize('expiry,expected', [
    ('not-a-date', 'unknown'), ('2026-02-30T00:00:00Z', 'unknown'), ('', 'unknown'),
    ('2026-10-24T00:00:00Z', 'stale'), ('2026-10-26T00:00:00Z', 'fresh'), (None, 'fresh'),
])
def test_explicit_malformed_expiry_cannot_fall_back_to_observation_age(expiry, expected):
    from src.app.services.accepted_catalog_projection import _freshness
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    assert _freshness(now, now=now, max_age_hours=24, expires_at=expiry) == expected


@pytest.mark.parametrize('operator,expected,observed,verdict', [
    ('=', 'GPU 10', 'GPU 100', 'below_minimum'),
    ('one_of', ['GPU 10'], 'GPU 10 Mobile', 'below_minimum'),
    ('in', ['CPU A', 'CPU B'], 'CPU B', 'meets_minimum'),
    ('<=', 32, 16, 'meets_minimum'),
    ('>=', 1, True, 'unknown'),
    ('>=', 16, float('nan'), 'unknown'),
    ('contains', 'CPU', 'CPU A', 'unknown'),
    ('=', '', 'CPU A', 'unknown'),
    ('=', False, 0, 'unknown'),
    ('=', False, False, 'meets_minimum'),
])
def test_exact_typed_fit_never_infers_hardware_equivalence(operator, expected, observed, verdict):
    from src.app.services.accepted_catalog_projection import _verdict
    assert _verdict({'operator': operator, 'value': expected}, observed) == verdict


def test_fresh_derived_catalog_observation_is_not_independently_verified():
    from src.app.services.accepted_catalog_projection import _evidence_for_attribute
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    observation = SimpleNamespace(
        id='derived-gpu', attribute_key='gpu_model', supersedes_id=None,
        value_json={'value':'GPU A'}, evidence_status='observed',
        claim_class='derived', observed_at=now, expires_at=None,
    )
    result = _evidence_for_attribute(None, 'gpu_model', [observation], now=now)
    assert result['observed'] == 'GPU A'
    assert result['claim_class'] == 'derived'
    assert result['verified'] is False


def project_accepted_catalog(db, **kwargs):
    # These reducer tests explicitly exercise every configuration in their
    # isolated seed. Buyer/tenant boundary tests live in test_case_catalog_candidates.
    kwargs.setdefault("candidate_configuration_ids", list(db.scalars(select(ProductConfiguration.id))))
    return _project_accepted_catalog(db, **kwargs)


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
    assert "shared:stretch" not in shelf_ids
    assert "conditional_scope:within_budget" in shelf_ids
    assert "architecture:desktop_workstation:within_budget" in shelf_ids
    assert not any(shelf.budget_band == "stretch" for shelf in projection.shelves)
    assert all(item.price_cents <= 600_000 for shelf in projection.shelves for item in shelf.initial + shelf.next_page)
    assert "local_vm:within_budget" in shelf_ids
    assert all(
        product.fit_status == "conditional"
        for shelf in projection.shelves for product in shelf.initial + shelf.next_page
    )
    assert all(len(shelf.initial) <= 3 and len(shelf.next_page) <= 5 for shelf in projection.shelves)


def test_generic_publisher_conditional_tier_is_projected_as_a_scoped_target():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(
            db,
            accepted_claims=[{
                "claim_id": "agisoft-advanced-ram",
                "attribute": "ram_gb",
                "operator": ">=",
                "value": 128,
                "requirement_class": "conditional",
                "condition": "Published tier: Advanced configuration",
                "authority_status": "case_origin_critic_accepted",
            }],
            desired_outcome="Large Agisoft Metashape drone surveys",
        )

    conditional = next(
        row for row in projection.shelves if row.scope_id == "conditional_scope"
    )
    candidates = [*conditional.initial, *conditional.next_page]
    assert candidates
    assert any(
        "ram gb" in [*candidate.meets, *candidate.unknowns, *candidate.misses]
        for candidate in candidates
    )
    assert all(
        "agisoft-advanced-ram" in candidate.requirement_claim_ids
        for candidate in candidates
    )


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


@pytest.mark.parametrize('authority', ['verified_pending', 'verified_fake', 'case_origin_critic_accepted'])
def test_authority_prefix_is_not_verified_evidence(authority):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(db, accepted_claims=[{
            'claim_id': 'held-ram', 'attribute': 'ram_gb', 'operator': '>=', 'value': 64,
            'requirement_class': 'minimum', 'authority_status': authority,
        }], now=datetime(2026, 8, 8, 12, tzinfo=timezone.utc))
    assert projection.shelves
    assert all(item.fit_status != 'qualified' for shelf in projection.shelves for item in shelf.initial + shelf.next_page)


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
    assert titan.fit_status == "conditional"
    assert titan.explanation is not None
    assert titan.explanation.evidence_basis == "conditional"
    assert "incomplete" in titan.explanation.summary
    assert titan.explanation.availability_note == (
        "Fresh availability evidence reports this configuration available."
    )
    assert titan.requirement_claim_ids == ["official-ram"]
    assert titan.capability_claim_ids
    assert titan.identity_evidence.status == "reconciled_oem_retailer"
    assert titan.identity_evidence.mpn == "Titan 18 HX A2WJ-1038AU"
    assert titan.identity_evidence.retailer_sku == "126982"
    assert titan.identity_evidence.claim_ids
    # This fixture evaluates Aug 8 but the specification is dated Aug 11.
    # Future observations are unknown, even when availability is current.
    assert titan.evidence_freshness.specification == "unknown"
    assert titan.evidence_freshness.price == "fresh"
    assert titan.evidence_freshness.availability == "fresh"
    assert {row.location_id for row in titan.availability} == {
        "australia_delivery", "dandenong",
    }
    assert all(row.freshness_status == "fresh" for row in titan.availability)


def test_quantity_projects_a_separate_deadline_shelf_through_shared_reducer():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(
            db,
            accepted_claims=[],
            requested_quantity=30,
            now=datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
        )

    deadline = next(
        row for row in projection.shelves
        if row.shelf_id == "shared:available_by_deadline"
    )
    assert deadline.decision_view == "available_by_deadline"
    products = [*deadline.initial, *deadline.next_page]
    assert products
    assert all(item.requested_quantity == 30 for item in products)
    assert all(
        item.quantity_fit in {"enough_now", "partial", "unavailable", "unknown"}
        for item in products
    )
    assert all(item.commercial_decision.cart_authority == "none" for item in products)


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
    assert zephyr.explanation is not None
    assert "not verified: cpu model" in zephyr.explanation.summary
    assert zephyr.explanation.claim_refs
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


def test_conflicting_oem_and_retailer_identity_is_visible_not_forced_to_exact_reconciliation():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        from src.app.models.orm import ProductConfiguration, ProductEvidenceObservation

        titan = db.query(ProductConfiguration).filter_by(sku="SCORP-126982").one()
        db.add(ProductEvidenceObservation(
            configuration_id=titan.id,
            attribute_key="manufacturer_part_number",
            value_json={"value": "OEM-DIFFERENT-CONFIG"},
            claim_class="attested",
            evidence_status="observed",
            source_id="MSI",
            source_record_id="https://www.msi.com/example#mpn",
            observed_at=datetime(2026, 8, 8, 12, tzinfo=timezone.utc),
        ))
        db.commit()
        projection = project_accepted_catalog(db, accepted_claims=[])

    products = {
        product.product.sku: product
        for shelf in projection.shelves
        for product in [*shelf.initial, *shelf.next_page]
    }
    assert products["SCORP-126982"].identity_evidence.status == "conflicted"


def test_only_exact_oem_pages_reconcile_retailer_identity():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        ingest_reviewed_configurations(db)
        projection = project_accepted_catalog(db, accepted_claims=[])

    products = {
        product.product.sku: product
        for shelf in projection.shelves
        for product in [*shelf.initial, *shelf.next_page]
    }
    assert products["SCORP-126982"].identity_evidence.status == "reconciled_oem_retailer"
    assert products["SCORP-125638"].identity_evidence.status == "reconciled_oem_retailer"
    assert products["SCORP-C07NXPT"].identity_evidence.status == "reconciled_oem_retailer"
    assert products["JW-822962"].identity_evidence.status == "retailer_attested"
    assert products["JW-818845"].identity_evidence.status == "retailer_attested"
