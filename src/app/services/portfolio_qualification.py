"""Explicit fictional evidence for a bounded buyer showcase, using existing reducers.

This adapter never changes real product facts, grants effects or contacts a provider.
All invented observations remain in the synthetic tenant and fixed replay clock.
"""
from datetime import datetime, timezone
import hashlib
import json
import uuid
from sqlalchemy import select, text
from src.app.models.orm import ShoppingCase, ProductConfiguration, ProductEvidenceObservation, ProductAvailabilityObservation
from src.app.services import case_contract_binding as bindings
from src.app.services.accepted_catalog_projection import project_accepted_catalog
from src.app.services.recommendation_core.requirement_scope import resolve_requirement_scope

TENANT='synthetic-electronics'
CONTRACT_ID='fictional-memory-lab-v1'
CONFIGURATION_ID='simulation:memory-lab:configuration-v1'
NOW=datetime(2026,9,26,0,0,tzinfo=timezone.utc)


def seed_configuration(db):
    existing=db.get(ProductConfiguration,CONFIGURATION_ID)
    if existing:
        if existing.tenant_id!=TENANT:
            raise ValueError('simulation_configuration_collision')
        return existing.id
    rows=db.execute(text('''SELECT p.id,p.sku,p.name,p.specs,p.price_cents FROM products p
        JOIN price_book_entry b ON b.sku=p.sku WHERE b.tenant_id=:tenant
        AND b.source='simulation:electronics-shortfall-v1' ORDER BY p.sku'''),{'tenant':TENANT}).all()
    candidates=[]
    for row in rows:
        specs=json.loads(row[3]) if isinstance(row[3],str) else row[3] or {}
        ram=specs.get('ram_gb')
        if row[1].startswith('LAP-') and type(ram) is int and ram>=32:
            candidates.append((row,ram))
    if not candidates:
        raise ValueError('synthetic_catalogue_not_seeded')
    row,ram=candidates[0]
    digest=hashlib.sha256(json.dumps({'sku':row[1],'ram_gb':ram,'simulation':CONTRACT_ID},sort_keys=True).encode()).hexdigest()
    db.add(ProductConfiguration(id=CONFIGURATION_ID,tenant_id=TENANT,product_id=row[0],sku=row[1],
        title='SIMULATED memory configuration — '+row[2],manufacturer='Fictional Manufacturer',
        retailer='Fictional Shop',mpn='SIM-'+row[1],retailer_sku=row[1],source_url='https://fixture.invalid/memory-v1',
        configuration_hash=digest,form_factor='laptop',device_class='laptop',mobility='mobile',
        ram_installed_gb=ram,price_cents=row[4],currency='AUD',specification_observed_at=NOW,
        price_observed_at=NOW,availability_observed_at=NOW))
    db.flush()
    db.add(ProductEvidenceObservation(configuration_id=CONFIGURATION_ID,attribute_key='ram_gb',
        value_json={'value':ram,'simulation_only':True},unit='GB',claim_class='attested',evidence_status='observed',
        source_id='simulation:shop-inventory',source_record_id='fixture:memory-v1',
        source_excerpt=f'Fictional configuration: {ram} GB RAM. Not manufacturer evidence.',observed_at=NOW))
    db.add(ProductAvailabilityObservation(configuration_id=CONFIGURATION_ID,location_id='simulation-network',
        status='in_stock',quantity=15,source_record_id='simulation:electronics-shortfall-v1',observed_at=NOW))
    db.flush()
    return CONFIGURATION_ID


def create_case(db, *, uid):
    if not uid or not db.get(ProductConfiguration,CONFIGURATION_ID):
        raise ValueError('synthetic_configuration_not_seeded_or_buyer_missing')
    case=ShoppingCase(case_id='simulation-'+str(uuid.uuid4()),tenant_id=TENANT,uid=uid,
                      revision=1,retained_purpose='simulation:'+CONTRACT_ID)
    db.add(case)
    db.flush()
    return {'case_id':case.case_id,'revision':case.revision,'contract_id':CONTRACT_ID,'tenant_id':TENANT}


def _claim():
    contract=bindings.load_contract_by_id(CONTRACT_ID)
    scope=resolve_requirement_scope(tenant_id=TENANT,profile_id='electronics',product_type='el-6-6',relationship='RUN_SUBJECT_ON_PRODUCT')
    return dict(claim_id='simulation:memory-requirement-v1',attribute='ram_gb',operator='>=',value=32,unit='GB',
        attribute_key='ram_gb',status='accepted',authority='official_requirements',confidence=1,
        source_record_id='simulation:memory-lab-v1',lineage_root='simulation:memory-lab-publisher',
        requirement_class='minimum',authority_status='verified_official',source_id='simulation:memory-lab-publisher',
        source_revision=contract.revision,source_excerpt='Fictional Memory Lab v1 requires 32 GB RAM; fixture only.',
        observed_at=NOW.isoformat(),applicability=contract.context.model_dump(),artefact_name=contract.context.subject,
        artefact_version=contract.context.version,compilation_scope=scope.model_dump(),simulation_only=True)


def project_case(db, *, case_id, uid, now=NOW):
    case=bindings._owned_case(db,tenant_id=TENANT,case_id=case_id,uid=uid)
    if case.retained_purpose!='simulation:'+CONTRACT_ID:
        raise ValueError('not_a_simulation_case')
    receipt=bindings.read_case_contract_binding(db,tenant_id=TENANT,case_id=case_id,uid=uid)
    selected=receipt.get('contract_id')==CONTRACT_ID and receipt['state']=='current'
    claim=_claim()
    from src.app.services.recommendation_core.requirement_compiler import compile_authoritative_requirements
    from src.app.services.recommendation_core.requirement_scope import RequirementScope
    from src.app.services.recommendation_core.case_binding import compilation_receipt
    contract=bindings.load_contract_by_id(CONTRACT_ID)
    compiled=compile_authoritative_requirements([claim] if selected else [],
        scope=RequirementScope.model_validate(claim['compilation_scope']),contract=contract,
        contract_context=contract.context,now=now)
    executable=selected and compiled.contract_coverage['compiled_complete']
    configuration=db.get(ProductConfiguration,CONFIGURATION_ID)
    stock=db.execute(text('SELECT location_id,available FROM inventory_level WHERE tenant_id=:tenant AND sku=:sku'),
        {'tenant':TENANT,'sku':configuration.sku}).all() if configuration else []
    availability=[ProductAvailabilityObservation(configuration_id=CONFIGURATION_ID,
        location_id=row.location_id,quantity=row.available,status='in_stock' if row.available>0 else 'sold_out',
        observed_at=now,source_record_id='simulation:canonical-inventory') for row in stock]
    projection=project_accepted_catalog(db,tenant_id=TENANT,case_id=case_id,uid=uid,
        accepted_claims=[claim] if executable else [],candidate_configuration_ids=[CONFIGURATION_ID] if executable else [],
        desired_outcome='Fictional Memory Lab v1: RAM capacity only',requested_quantity=1,now=now,
        availability_observations=availability)
    if selected:
        bindings.assert_case_contract_unchanged(db,tenant_id=TENANT,case_id=case_id,uid=uid,receipt=receipt)
    result=projection.model_dump(mode='json')
    return dict(simulation_only=True,commerce_authority='none',case_id=case_id,case_revision=case.revision,
        scenario_time=now.isoformat(),projection=result,
        trace={'requirement_contract':result['requirement_contract'],'requirement_claim':claim,
               'compilation':compilation_receipt(compiled),
               'configuration_id':CONFIGURATION_ID,'commerce_authority':'none'})
