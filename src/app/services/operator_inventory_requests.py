"""Person-approved exact inventory requests; internal service, caller owns commit."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from sqlalchemy import text
from src.app.services.inventory_transactions import _atomic, move_stock, transition
from src.app.services.fulfillment import person_approval

REQUEST_DDL='''CREATE TABLE IF NOT EXISTS operator_inventory_request (
 id VARCHAR(64) PRIMARY KEY,tenant_id VARCHAR(128) NOT NULL,source_reference VARCHAR(200) NOT NULL,
 requester_principal VARCHAR(64) NOT NULL,payload_json TEXT NOT NULL,payload_digest VARCHAR(64) NOT NULL,
 value_cents INTEGER NOT NULL,currency VARCHAR(3) NOT NULL,status VARCHAR(32) NOT NULL,
 approval_id VARCHAR(64),result_json TEXT,created_at TEXT NOT NULL,
 UNIQUE(tenant_id,source_reference))'''


def _hash(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def effect_digest(*, tenant_id, actor_id, action_id, requester_principal, payload,
                  value_cents, currency, person_approval_id):
    return _hash(dict(policy_version='inventory-person-effect-v1',tenant_id=tenant_id,
        actor_id=actor_id,action_id=action_id,requester_principal=requester_principal,payload=payload,
        value_cents=value_cents,currency=currency,person_approval_id=person_approval_id))


def get_request(db, *, tenant_id, request_id):
    row=db.execute(text('SELECT * FROM operator_inventory_request WHERE tenant_id=:tenant AND id=:id'),
        dict(tenant=tenant_id,id=request_id)).mappings().first()
    if not row:raise ValueError('inventory_request_not_found')
    return dict(row)


def _case_reservation(db, *, tenant_id,case_id,case_revision,reservation_id,sku):
    case=db.execute(text('SELECT revision FROM shopping_cases WHERE tenant_id=:tenant AND case_id=:case'),
        dict(tenant=tenant_id,case=case_id)).first()
    if not case or type(case_revision) is not int or case[0]!=case_revision:
        raise ValueError('inventory_case_revision_conflict')
    row=db.execute(text('''SELECT r.* FROM inventory_reservation r
        JOIN shopping_case_fulfillment_selections s ON s.tenant_id=r.tenant_id
          AND r.reservation_id LIKE 'selection:' || s.selection_id || ':%'
        WHERE r.tenant_id=:tenant AND r.reservation_id=:reservation AND r.sku=:sku
          AND s.case_id=:case AND s.revision=:revision'''),
        dict(tenant=tenant_id,reservation=reservation_id,sku=sku,case=case_id,revision=case_revision)).mappings().first()
    if not row:raise ValueError('reservation_case_binding_required')
    return dict(row)


def create_request(db, *, tenant_id, requester_principal, kind, sku,
                   source_reference, quantity, destination_location=None,source_location=None,
                   reservation_id=None,case_id=None,case_revision=None):
    person_approval._person(db,tenant_id,requester_principal)
    if type(quantity) is not int or not 1<=quantity<=10000:
        raise ValueError('invalid_movement_quantity')
    lifecycle=kind in ('ship','cancel','return')
    if kind not in ('receive','transfer','ship','cancel','return') or not all((sku,source_reference)):
        raise ValueError('invalid_movement_request')
    if lifecycle:
        if destination_location is not None or source_location is not None:
            raise ValueError('reservation_controls_inventory_location')
        hold=_case_reservation(db,tenant_id=tenant_id,case_id=case_id,case_revision=case_revision,
            reservation_id=reservation_id,sku=sku)
        if kind!='return' and quantity!=hold['quantity']:
            raise ValueError('whole_reservation_transition_required')
    elif any(value is not None for value in (reservation_id,case_id,case_revision)) or not destination_location:
        raise ValueError('invalid_stock_movement_binding')
    if kind=='transfer' and (not source_location or source_location==destination_location):
        raise ValueError('distinct_transfer_locations_required')
    if kind=='receive' and source_location is not None:
        raise ValueError('receipt_cannot_have_source_location')
    product=db.execute(text('SELECT price_cents,currency FROM products WHERE sku=:sku'),{'sku':sku}).first()
    if not product or type(product[0]) is not int or product[0]<0 or not product[1]:
        raise ValueError('server_inventory_valuation_required')
    locations=[] if lifecycle else [destination_location]+([source_location] if source_location else [])
    for location in locations:
        if not db.execute(text('SELECT 1 FROM inventory_level WHERE tenant_id=:tenant AND sku=:sku AND location_id=:location'),
            dict(tenant=tenant_id,sku=sku,location=location)).first():
            raise ValueError('scoped_inventory_location_required')
    payload=dict(tenant_id=tenant_id,source_reference=source_reference,kind=kind,sku=sku,
        destination_location=destination_location,source_location=source_location,quantity=quantity)
    if lifecycle:
        payload.update(reservation_id=reservation_id,case_id=case_id,case_revision=case_revision)
    fingerprint=_hash(dict(payload=payload,requester=requester_principal,value=quantity*product[0],currency=product[1]))
    params=dict(id=str(uuid.uuid4()),tenant=tenant_id,source=source_reference,requester=requester_principal,
        payload=json.dumps(payload,sort_keys=True),digest=fingerprint,value=quantity*product[0],currency=product[1],
        now=datetime.now(timezone.utc).isoformat())
    db.execute(text('''INSERT INTO operator_inventory_request
        (id,tenant_id,source_reference,requester_principal,payload_json,payload_digest,value_cents,currency,status,created_at)
        VALUES (:id,:tenant,:source,:requester,:payload,:digest,:value,:currency,'pending',:now)
        ON CONFLICT(tenant_id,source_reference) DO NOTHING'''),params)
    row=db.execute(text('SELECT * FROM operator_inventory_request WHERE tenant_id=:tenant AND source_reference=:source'),params).mappings().one()
    if row['payload_digest']!=fingerprint:raise ValueError('inventory_request_conflict')
    return dict(row)


def _effect(row, approver):
    return dict(tenant_id=row['tenant_id'],actor_id=approver,action_id=row['id'],
        requester_principal=row['requester_principal'],payload=json.loads(row['payload_json']),
        value_cents=row['value_cents'],currency=row['currency'])


def approve_request(db, *, tenant_id,request_id,approver_principal,now=None):
    clock=now or datetime.now(timezone.utc)
    with _atomic(db):
        row=get_request(db,tenant_id=tenant_id,request_id=request_id)
        if row['status']!='pending':raise ValueError('inventory_request_not_pending')
        grant=person_approval.issue(db,requester_principal=row['requester_principal'],
            approver_principal=approver_principal,effect=_effect(row,approver_principal),
            value_cents=row['value_cents'],expires_at=clock+timedelta(hours=1),now=clock,
            digest_builder=effect_digest)
        changed=db.execute(text("UPDATE operator_inventory_request SET status='approved',approval_id=:grant "
            "WHERE tenant_id=:tenant AND id=:id AND status='pending'"),
            dict(grant=grant['id'],tenant=tenant_id,id=request_id))
        if changed.rowcount!=1:raise ValueError('inventory_request_approval_conflict')
        return get_request(db,tenant_id=tenant_id,request_id=request_id)


def execute_request(db, *, tenant_id,request_id,now=None):
    with _atomic(db):
        row=get_request(db,tenant_id=tenant_id,request_id=request_id)
        if row['status']=='completed':
            return dict(status='completed',request_id=request_id,result=json.loads(row['result_json']))
        if row['status']!='approved' or not row['approval_id']:
            raise ValueError('approved_inventory_request_required')
        grant=db.execute(text('SELECT approver_principal FROM person_effect_approval WHERE tenant_id=:tenant AND id=:id'),
            dict(tenant=tenant_id,id=row['approval_id'])).first()
        if not grant:raise ValueError('person_approval_required')
        digest=effect_digest(**_effect(row,grant[0]),person_approval_id=row['approval_id'])
        person_approval.validate(db,tenant_id=tenant_id,approval_id=row['approval_id'],digest=digest,now=now)
        payload=json.loads(row['payload_json'])
        if payload['kind'] in ('ship','cancel','return'):
            _case_reservation(db,**{key:payload[key] for key in ('tenant_id','case_id','case_revision','reservation_id','sku')})
            result=transition(db,tenant_id=tenant_id,reservation_id=payload['reservation_id'],kind=payload['kind'],
                event_id=payload['source_reference'],quantity=payload['quantity'] if payload['kind']=='return' else None,now=now)
        else:
            result=move_stock(db,**payload)
        db.execute(text("UPDATE operator_inventory_request SET status='completed',result_json=:result WHERE tenant_id=:tenant AND id=:id"),
            dict(result=json.dumps(result,sort_keys=True),tenant=tenant_id,id=request_id))
        return dict(status='completed',request_id=request_id,result=result)
