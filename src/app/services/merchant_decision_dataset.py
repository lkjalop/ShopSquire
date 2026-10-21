"""Observed, scoped inputs and an advisory replenishment baseline.

Synthetic latent demand remains outside this contract. None of these functions
grant authority to reserve stock, send messages or purchase goods.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
import statistics

from src.app.services.inventory_event_projection import project_inventory_events


def _utc(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build_dataset(replay, *, as_of):
    cutoff = _utc(as_of)
    manifest = replay['manifest']
    binding = manifest['catalog_binding']
    if not manifest['tenant_id'].startswith('synthetic-'):
        raise ValueError('synthetic_dataset_required')
    observations = [row for row in replay['observations'] if _utc(row.event_time) <= cutoff]
    daily = []
    for row in replay['history']['daily_history']:
        # The observation is a completed day, available after its 23:00 close.
        observed = _utc(row['date'] + 'T23:00:00+00:00')
        if observed > cutoff:
            continue
        daily.append({key:row[key] for key in (
            'date', 'opening_on_hand_units', 'receipt_units',
            'observed_sales_units', 'closing_on_hand_units')})
        daily[-1].update(coverage='complete', available_at=observed.isoformat(),
                         stockout_censored=row['closing_on_hand_units'] == 0)
    reconciliation = project_inventory_events(observations, tenant_id=manifest['tenant_id'],
        source=manifest['source'], default_location_id='location:primary')
    reservations={}
    for observation in sorted(observations,key=lambda row:(_utc(row.event_time),row.external_id)):
        if observation.entity_type=='reservation':
            previous=reservations.get(observation.external_id)
            if previous and _utc(previous.event_time)==_utc(observation.event_time) and previous.payload!=observation.payload:
                raise ValueError('ambiguous_commitment_observation')
            reservations[observation.external_id]=observation
    commitments=[]
    for identity,observation in sorted(reservations.items()):
        payload=observation.payload
        if payload['variant_id']!=binding['target_variant_id'] or payload['status']!='held':continue
        if payload.get('expires_at') and _utc(payload['expires_at'])<=cutoff:continue
        quantity=payload['quantity']
        if quantity['uom']!='EA' or type(quantity['value']) is not int:
            raise ValueError('commitment_requires_integer_units')
        commitments.append(dict(source_reference=identity,quantity_units=quantity['value'],
            location_id=payload['location_id'],observed_at=observation.event_time,expires_at=payload.get('expires_at')))
    start=date.fromisoformat(manifest['start_date'])
    incoming_schedule=[]
    for row in replay['history']['purchase_orders']:
        if row['order_date']>cutoff.date().isoformat():continue
        eta=start+timedelta(days=row['receipt_day'])
        if eta<=cutoff.date() or row.get('status')=='cancelled':continue
        incoming_schedule.append(dict(quantity_units=row['quantity_units'],expected_date=eta.isoformat(),
            ordered_at=row['order_date'],status='expected',certainty='simulated_schedule',
            source_reference=row.get('purchase_order_id') or _digest(row)))
    incoming_schedule.sort(key=lambda row:(row['expected_date'],row['source_reference']))
    incoming=sum(row['quantity_units'] for row in incoming_schedule)
    result = dict(schema_version=2, tenant_id=manifest['tenant_id'], sku=binding['target_variant_id'],
        currency=binding['currency'], as_of=cutoff.isoformat(), daily=daily,
        reconciliation=reconciliation, incoming_units=incoming,incoming_schedule=incoming_schedule,
        commitments=commitments,committed_units=sum(row['quantity_units'] for row in commitments),
        source_id='simulation:'+manifest['parameter_hash'],
        simulation_only=True, commerce_authority='none')
    result['lifecycle_counts'] = {
        'returns': sum(o.entity_type=='return' for o in observations),
        'cancelled_orders': sum(o.entity_type=='order' and o.payload.get('status')=='cancelled' for o in observations),
        'receipts': sum(o.entity_type=='receipt' for o in observations),
        'transfers': sum(o.entity_type=='transfer' for o in observations),
    }
    result['dataset_id'] = _digest(result)
    return result


def reorder_baseline(dataset, *, quote, now, lookback_days=28, safety_days=3):
    clock = _utc(now)
    def blocked(reason):
        return dict(status='blocked', reason=reason, commerce_authority='none',
                    simulation_only=bool(dataset.get('simulation_only')))
    if not dataset.get('simulation_only') or quote.get('simulation_only') is not True:
        return blocked('simulation_scope_required')
    if any(quote.get(key) != dataset.get(key) for key in ('tenant_id','sku','currency')):
        return blocked('quote_scope_mismatch')
    if not quote.get('source_id') or not quote.get('supplier_id'):
        return blocked('quote_provenance_required')
    try:
        if not _utc(quote['observed_at']) <= clock < _utc(quote['expires_at']):
            return blocked('quote_not_current')
        if not timedelta(0) <= clock-_utc(dataset['as_of']) <= timedelta(days=1):
            return blocked('dataset_not_current')
    except (KeyError, ValueError, TypeError):
        return blocked('invalid_evidence_time')
    projection = dataset.get('reconciliation') or {}
    if (projection.get('balance_integrity',{}).get('status') != 'passed'
            or projection.get('atp_reconciliation',{}).get('status') != 'matched'
            or projection.get('conservation',{}).get('status') != 'passed'):
        return blocked('inventory_not_reconciled')
    days = dataset.get('daily',[])[-lookback_days:]
    end = _utc(dataset['as_of']).date()
    expected = [(end-timedelta(days=i)).isoformat() for i in reversed(range(lookback_days))]
    if [row['date'] for row in days] != expected or any(row.get('coverage')!='complete' for row in days):
        return blocked('daily_coverage_incomplete')
    for key in ('lead_time_days','capacity_units','minimum_order_units','landed_unit_cost_minor'):
        if type(quote.get(key)) is not int or quote[key] <= 0:
            return blocked('invalid_supplier_terms')
    if quote['capacity_units'] < quote['minimum_order_units']:
        return blocked('supplier_capacity_below_minimum')
    mean = statistics.fmean(row['observed_sales_units'] for row in days)
    available = sum(row['quantity'] for row in projection['balances']
                    if row['custody']=='available' and row['variant_id']==dataset['sku'])
    if not isinstance(dataset.get('incoming_schedule'),list):
        return blocked('incoming_schedule_required')
    horizon_end=(clock+timedelta(days=quote['lead_time_days']+safety_days)).date().isoformat()
    within_horizon=sum(row['quantity_units'] for row in dataset['incoming_schedule']
        if row['status']=='expected' and clock.date().isoformat()<row['expected_date']<=horizon_end)
    committed=dataset.get('committed_units')
    if type(committed) is not int or committed<0:return blocked('commitment_evidence_required')
    position = available-committed+within_horizon
    target = math.ceil(mean*(quote['lead_time_days']+safety_days))
    required = max(0, target-position)
    proposed = max(quote['minimum_order_units'], required) if required else 0
    quantity = min(quote['capacity_units'], proposed)
    censored = sum(row['stockout_censored'] for row in days)
    return dict(status='advisory', decision='review_replenishment' if quantity else 'wait_and_monitor',
        tenant_id=dataset['tenant_id'], sku=dataset['sku'], currency=dataset['currency'],
        available_units=available, incoming_units=dataset['incoming_units'], inventory_position=position,
        incoming_within_horizon_units=within_horizon,
        committed_units=committed,
        late_incoming_units=dataset['incoming_units']-within_horizon,decision_horizon_end=horizon_end,
        observed_mean_daily=mean, target_units=target, proposed_units=quantity,
        uncovered_units=max(0,required-quantity), total_cost_minor=quantity*quote['landed_unit_cost_minor'],
        censored_days=censored, demand_basis='observed_sales_lower_bound' if censored else 'observed_sales',
        explanation='Compare observed sales over the supplier lead time plus safety days with available stock and incoming units expected within that horizon.',
        limitation='Observed sales may understate demand on stockout days.' if censored else None,
        evidence_ids=[dataset['dataset_id'], dataset['source_id'], quote['source_id']],
        simulation_only=True, commerce_authority='none', baseline_version='reorder-observed-v2')


def persist_snapshot(db, *, dataset, quote, evidence_documents=None):
    """Append immutable inputs; callers own the transaction. No operational effects."""
    from sqlalchemy import text
    if not dataset.get('simulation_only') or not dataset['tenant_id'].startswith('synthetic-'):
        raise ValueError('synthetic_dataset_required')
    document = dict(dataset=dataset, quote=quote)
    if evidence_documents is not None:
        document['evidence_documents']=evidence_documents
    identity = _digest(document)
    db.execute(text('''INSERT INTO merchant_decision_dataset
        (id,tenant_id,sku,as_of,document_json,created_at)
        VALUES (:id,:tenant,:sku,:as_of,:document,:created)
        ON CONFLICT(id) DO NOTHING'''),
        dict(id=identity,tenant=dataset['tenant_id'],sku=dataset['sku'],as_of=dataset['as_of'],
             document=json.dumps(document,sort_keys=True),created=datetime.now(timezone.utc).isoformat()))
    return identity


def latest_snapshot(db, *, tenant_id, sku):
    from sqlalchemy import text
    row = db.execute(text('''SELECT id,document_json FROM merchant_decision_dataset
        WHERE tenant_id=:tenant AND sku=:sku ORDER BY as_of DESC,created_at DESC,id DESC LIMIT 1'''),
        dict(tenant=tenant_id,sku=sku)).first()
    if row is None:
        return None
    return dict(id=row[0], **json.loads(row[1]))
