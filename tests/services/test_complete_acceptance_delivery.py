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
              'os':'Windows 11', 'storage_gb':1000, 'storage_type':'SSD'}
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
        def project(rows, budget=300000, stretch=None):
            return project_accepted_catalog(db, accepted_claims=rows, candidate_configuration_ids=[product.id],
                budget_cents=budget, stretch_budget_cents=stretch, requested_quantity=2, now=now)
        complete = project(claims)
        assert complete.shelves
        assert any(item.fit_status == 'qualified' for shelf in complete.shelves for item in shelf.initial), [
            (item.conditional, item.explanation.summary) for shelf in complete.shelves for item in shelf.initial]
        partial = project(claims[:1])
        assert partial.shelves
        assert all(item.fit_status != 'qualified' for shelf in partial.shelves for item in shelf.initial)
        assert not project(claims, budget=100000).shelves
        bounded = project(claims, budget=100000, stretch=210000)
        assert bounded.shelves
        assert any(shelf.budget_band == 'stretch' for shelf in bounded.shelves)
        assert all(item.price_cents <= 210000 for shelf in bounded.shelves for item in shelf.initial)
        # Exercise the connector -> compiler -> ledger -> fit boundary, rather
        # than only injecting already-accepted claims into the final stage.
        from src.app.services.recommendation_core.workload_grounding import compile_workload_evidence_requirements
        from src.app.services.structured_requirement_claims import project_structured_requirement_claims
        minimum = {'ram_gb':32, 'storage_gb':1000, 'cpu':'Fixture CPU',
                   'gpu':'Fixture GPU', 'os':'Windows 11', 'storage_type':'SSD'}
        minimum['source_fields'] = {key: {'text': minimum[key], 'start':0,
            'end':len(minimum[key]), 'representation':'steam_requirement_line_v1'}
            for key in ('cpu', 'gpu', 'os', 'storage_type')}
        compiled = compile_workload_evidence_requirements({
            'source':'steam', 'app_id':'synthetic', 'confidence':1,
            'canonical_title':'Synthetic workload', 'retrieved_at':now.isoformat(),
            'minimum':minimum}, kind='game', name='Synthetic workload', product_type='el-6-6')
        ledger = project_structured_requirement_claims({'evidence':[{
            'status':'resolved', 'source':'steam', 'app_id':'synthetic',
            'compiled_requirements':[row.model_dump() for row in compiled.requirements]}]})
        delivered = project(ledger)
        from src.app.services.accepted_catalog_projection import _verdict
        for claim in ledger:
            assert _verdict(claim, values[claim['attribute']]) == 'meets_minimum', claim
        assert any(item.fit_status == 'qualified' for shelf in delivered.shelves for item in shelf.initial), delivered.model_dump(mode='json')
        # More VRAM is not an independently reviewed GPU equivalence.
        for claim in ledger:
            if claim['attribute'] == 'gpu_model':
                claim['value'] = ['Different GPU']
        incompatible = project(ledger)
        assert all(item.fit_status != 'qualified' for shelf in incompatible.shelves for item in shelf.initial)
