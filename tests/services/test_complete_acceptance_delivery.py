from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.app.models.orm import Base, ProductConfiguration, ProductEvidenceObservation, ProductAvailabilityObservation
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope


def test_complete_fixture_evidence_delivers_but_partial_evidence_never_qualifies():
    now = datetime(2026, 9, 10, tzinfo=timezone.utc)
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    scope = resolve_requirement_scope(tenant_id='default', profile_id='electronics',
        product_type='el-6-6', relationship='RUN_SUBJECT_ON_PRODUCT')
    values = {'ram_gb':32, 'cpu_model':'Fixture CPU', 'gpu_model':'Fixture GPU',
              'os':'Fixture OS', 'storage_gb':1000, 'storage_type':'SSD'}
    with Session(engine) as db:
        product = ProductConfiguration(id='fixture-config', tenant_id='default', sku='FIXTURE',
            title='Synthetic complete configuration', mpn='FIXTURE-MPN', configuration_hash='fixture-hash', price_cents=200000,
            device_class='gaming_laptop', form_factor='laptop', mobility='portable',
            specification_observed_at=now, price_observed_at=now, availability_observed_at=now)
        db.add(product)
        for attribute, value in values.items():
            db.add(ProductEvidenceObservation(configuration_id=product.id, attribute_key=attribute,
                value_json={'value':value}, claim_class='attested', evidence_status='observed',
                source_id='isolated-test-fixture', source_record_id=f'fixture:{attribute}', observed_at=now))
        db.add(ProductAvailabilityObservation(configuration_id=product.id, location_id='fixture-location',
            status='available', quantity=10, source_record_id='fixture:stock', observed_at=now))
        db.commit()
        claims = [{'claim_id':key, 'attribute':key, 'operator':'=', 'value':value,
            'requirement_class':'minimum', 'authority_status':'verified_official',
            'artefact_name':'Synthetic workload', 'compilation_scope':scope.model_dump(mode='json')}
            for key,value in values.items()]
        def project(rows, budget=300000):
            return project_accepted_catalog(db, accepted_claims=rows, candidate_configuration_ids=[product.id],
                budget_cents=budget, requested_quantity=2, now=now)
        complete = project(claims)
        assert complete.shelves
        assert any(item.fit_status == 'qualified' for shelf in complete.shelves for item in shelf.initial), [
            (item.conditional, item.explanation.summary) for shelf in complete.shelves for item in shelf.initial]
        partial = project(claims[:1])
        assert partial.shelves
        assert all(item.fit_status != 'qualified' for shelf in partial.shelves for item in shelf.initial)
        assert not project(claims, budget=100000).shelves
