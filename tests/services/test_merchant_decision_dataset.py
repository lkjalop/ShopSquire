from copy import deepcopy
from datetime import date, datetime, timezone
import pytest
from src.app.services.synthetic_canonical_replay import materialize_canonical_replay
from src.app.services import merchant_decision_dataset as service


@pytest.fixture
def replay():
    return materialize_canonical_replay('electronics_memory_allocation', seed=41, days=180,
        tenant_id='synthetic-market-pilot', start_date=date(2026,4,4),
        target_variant_id='LAP-01B48B57', currency='AUD', include_lifecycle_probes=False)


def test_observed_dataset_excludes_oracle_and_future_days(replay):
    dataset=service.build_dataset(replay, as_of=datetime(2026,9,1,23,59,tzinfo=timezone.utc))
    assert dataset['daily'][-1]['date']=='2026-09-01'
    assert all('latent_demand_units' not in day and 'lost_sales_units' not in day for day in dataset['daily'])
    assert dataset['reconciliation']['balance_integrity']['status']=='passed'
    assert dataset['reconciliation']['atp_reconciliation']['status']=='matched'
    assert dataset['commerce_authority']=='none'
    changed=deepcopy(replay)
    for day in changed['history']['daily_history']:
        day['latent_demand_units']=99999
        if day['date']>'2026-09-01':day['observed_sales_units']=99999
    assert service.build_dataset(changed, as_of=datetime(2026,9,1,23,59,tzinfo=timezone.utc))==dataset


def test_baseline_requires_current_scoped_terms_and_reports_censoring(replay):
    now=datetime(2026,9,30,23,59,tzinfo=timezone.utc)
    data=service.build_dataset(replay,as_of=now)
    quote={'tenant_id':data['tenant_id'],'sku':data['sku'],'currency':'AUD','supplier_id':'fake-supplier',
        'lead_time_days':9,'capacity_units':100,'minimum_order_units':1,'landed_unit_cost_minor':98000,
        'observed_at':'2026-09-30T00:00:00+00:00','expires_at':'2026-10-02T00:00:00+00:00',
        'source_id':'simulation:quote-1','simulation_only':True}
    out=service.reorder_baseline(data,quote=quote,now=now)
    assert out['status']=='advisory'
    assert out['commerce_authority']=='none'
    assert out['evidence_ids']
    assert out['censored_days']>=0
    for bad in [{'sku':'OTHER'},{'tenant_id':'other'},{'currency':'USD'},
                {'expires_at':'2026-09-29T00:00:00+00:00'}]:
        assert service.reorder_baseline(data,quote={**quote,**bad},now=now)['status']=='blocked'
    broken=deepcopy(data);broken['daily'].pop(-2)
    assert service.reorder_baseline(broken,quote=quote,now=now)['status']=='blocked'
    assert service.reorder_baseline(data,quote={**quote,'minimum_order_units':200},now=now)['status']=='blocked'


def test_snapshot_replay_and_reads_are_tenant_bound(replay):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    engine=create_engine('sqlite:///:memory:')
    with Session(engine) as db:
        db.execute(text('CREATE TABLE merchant_decision_dataset(id TEXT PRIMARY KEY, tenant_id TEXT, sku TEXT, as_of TEXT, document_json TEXT, created_at TEXT)'))
        data=service.build_dataset(replay,as_of=datetime(2026,9,30,23,59,tzinfo=timezone.utc))
        first=service.persist_snapshot(db,dataset=data,quote={'source_id':'simulation:test'})
        assert service.persist_snapshot(db,dataset=data,quote={'source_id':'simulation:test'})==first
        assert db.execute(text('SELECT COUNT(*) FROM merchant_decision_dataset')).scalar_one()==1
        assert service.latest_snapshot(db,tenant_id=data['tenant_id'],sku=data['sku'])['id']==first
        assert service.latest_snapshot(db,tenant_id='other',sku=data['sku']) is None
        assert service.latest_snapshot(db,tenant_id=data['tenant_id'],sku='other') is None
    engine.dispose()


def test_inbound_eta_changes_horizon_availability_not_just_total(replay):
    now=datetime(2026,9,30,23,59,tzinfo=timezone.utc)
    elapsed=(now.date()-date.fromisoformat(replay['manifest']['start_date'])).days
    near=deepcopy(replay)
    near['history']['purchase_orders']=[dict(order_date='2026-09-30',receipt_day=elapsed+2,quantity_units=100)]
    far=deepcopy(near);far['history']['purchase_orders'][0]['receipt_day']+=365
    first=service.build_dataset(near,as_of=now);second=service.build_dataset(far,as_of=now)
    assert first['dataset_id']!=second['dataset_id']
    quote=dict(tenant_id=first['tenant_id'],sku=first['sku'],currency='AUD',supplier_id='fake',
        lead_time_days=9,capacity_units=100,minimum_order_units=1,landed_unit_cost_minor=98000,
        observed_at=now.isoformat(),expires_at='2026-10-02T00:00:00+00:00',source_id='simulation:quote',simulation_only=True)
    a=service.reorder_baseline(first,quote=quote,now=now)
    b=service.reorder_baseline(second,quote=quote,now=now)
    assert a['incoming_within_horizon_units']==100
    assert b['incoming_within_horizon_units']==0
    assert a['inventory_position']-b['inventory_position']==100
    assert b['late_incoming_units']==100


def test_legacy_undated_incoming_cannot_support_decision(replay):
    now=datetime(2026,9,30,23,59,tzinfo=timezone.utc)
    data=service.build_dataset(replay,as_of=now)
    data.pop('incoming_schedule',None)
    quote=dict(tenant_id=data['tenant_id'],sku=data['sku'],currency='AUD',supplier_id='fake',
        lead_time_days=9,capacity_units=100,minimum_order_units=1,landed_unit_cost_minor=98000,
        observed_at=now.isoformat(),expires_at='2026-10-02T00:00:00+00:00',source_id='simulation:quote',simulation_only=True)
    assert service.reorder_baseline(data,quote=quote,now=now)['reason']=='incoming_schedule_required'


def test_current_commitments_expiry_and_release_share_observation_cutoff(replay):
    from src.app.services.authoritative_business_feed import BusinessObservation
    now=datetime(2026,9,30,23,59,tzinfo=timezone.utc)
    def reservation(identity,status,event_time,expires_at):
        return BusinessObservation(entity_type='reservation',external_id=identity,event_time=event_time,
            payload=dict(variant_id='LAP-01B48B57',location_id='location:primary',quantity={'value':4,'uom':'EA'},
                         status=status,expires_at=expires_at,idempotency_key=identity+status))
    replay['observations']+= [reservation('active','held','2026-09-30T10:00:00+00:00','2026-10-01T10:00:00+00:00'),
        reservation('expired','held','2026-09-30T10:00:00+00:00','2026-09-30T11:00:00+00:00'),
        reservation('released','held','2026-09-30T10:00:00+00:00','2026-10-01T10:00:00+00:00'),
        reservation('released','released','2026-09-30T11:00:00+00:00','2026-10-01T10:00:00+00:00'),
        reservation('active','released','2026-10-01T09:00:00+00:00','2026-10-01T10:00:00+00:00')]
    dataset=service.build_dataset(replay,as_of=now)
    assert dataset['committed_units']==4
    assert [row['source_reference'] for row in dataset['commitments']]==['active']
    assert dataset['reconciliation']['balance_integrity']['status']=='passed'


def test_operational_lifecycle_is_reconciled_in_the_same_snapshot(replay):
    from src.app.adapters.synthetic_market_operations import append_after_close_operations
    now=datetime(2026,9,30,23,59,tzinfo=timezone.utc)
    augmented=append_after_close_operations(replay,as_of=now.isoformat())
    dataset=service.build_dataset(augmented,as_of=now)
    for field in ('returns','cancelled_orders','transfers'):
        assert dataset['lifecycle_counts'][field]>0
    assert dataset['committed_units']==1
    assert dataset['reconciliation']['balance_integrity']['status']=='passed'
    assert dataset['reconciliation']['atp_reconciliation']['status']=='matched'
    assert dataset['reconciliation']['conservation']['status']=='passed'
    original=service.build_dataset(replay,as_of=now)
    before=service.build_dataset(augmented,as_of=now.replace(hour=23,minute=0))
    assert before['committed_units']==0
    assert before['reconciliation']['balances']==original['reconciliation']['balances']
