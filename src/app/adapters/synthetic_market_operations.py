"""Explicit after-close fictional events over an existing scoped replay.

These events are not inferred from demand or silently added to historical sales.
The daily observations remain observations at their recorded 23:00 close; the
current inventory snapshot also includes these later operational events.
"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime,timedelta
import hashlib
import json

from src.app.services.authoritative_business_feed import BusinessObservation


def append_after_close_operations(replay, *, as_of):
    result=deepcopy(replay)
    binding=result['manifest']['catalog_binding']
    if not result['manifest']['tenant_id'].startswith('synthetic-'):
        raise ValueError('synthetic_tenant_required')
    clock=datetime.fromisoformat(as_of.replace('Z','+00:00'))
    if clock.tzinfo is None or (clock.hour,clock.minute)<(23,30):
        raise ValueError('after_close_scenario_clock_required')
    sku=binding['target_variant_id'];currency=binding['currency'];day=clock.date().isoformat()
    # Use the existing end-of-day available balance, then record all deltas.
    from src.app.services.inventory_event_projection import project_inventory_events
    prior=project_inventory_events([o for o in result['observations'] if datetime.fromisoformat(o.event_time.replace('Z','+00:00'))<=clock],
        tenant_id=result['manifest']['tenant_id'],source=result['manifest']['source'])
    available={r['location_id']:r['quantity'] for r in prior['balances'] if r['variant_id']==sku and r['custody']=='available'}
    def qty(value):return dict(value=value,uom='EA')
    def money(value):return dict(amount_minor=value,currency=currency)
    events=[]
    def add(kind,identity,minute,payload):
        events.append(BusinessObservation(entity_type=kind,external_id='simulation:operations:'+identity,
            event_time=f'{day}T23:{minute:02d}:00+00:00',payload=payload))
    add('receipt','receipt',5,dict(purchase_order_external_id='simulation:operations:po',variant_id=sku,
        location_id='location:primary',quantity=qty(4),custody_status='accepted',ownership_status='owned'))
    add('order','fulfilled',10,dict(party_external_id='simulation:buyer',status='fulfilled',total=money(100)))
    add('order_line','fulfilled-line',10,dict(order_external_id='simulation:operations:fulfilled',variant_id=sku,
        location_id='location:primary',quantity=qty(1),unit_price=money(100)))
    add('return','return',11,dict(order_external_id='simulation:operations:fulfilled',variant_id=sku,
        location_id='location:primary',quantity=qty(1),physical_disposition='restock',financial_disposition='refunded'))
    add('order','cancelled',12,dict(party_external_id='simulation:buyer',status='cancelled',total=money(0)))
    add('transfer','transfer',13,dict(variant_id=sku,from_location_id='location:primary',to_location_id='location:secondary',
        quantity=qty(2),status='received'))
    add('reservation','commitment',14,dict(variant_id=sku,location_id='location:primary',quantity=qty(1),status='held',
        expires_at=(clock+timedelta(hours=12)).isoformat(),idempotency_key='simulation:operations:commitment'))
    for location,delta in [('location:primary',2),('location:secondary',2)]:
        add('location_atp','checkpoint:'+location,20,dict(variant_id=sku,location_id=location,
            source_atp=qty(available.get(location,0)+delta),source_basis=['explicit_after_close_fixture_events'],
            source_calculated_at=f'{day}T23:20:00+00:00',ttl_seconds=86400))
    result['observations']+=events
    manifest=result['manifest']
    manifest['after_close_operations']='simulation:operations-v1'
    manifest['parameter_hash']=hashlib.sha256(json.dumps(dict(base=manifest['parameter_hash'],
        events=[asdict(e) for e in events]),sort_keys=True).encode()).hexdigest()
    return result
