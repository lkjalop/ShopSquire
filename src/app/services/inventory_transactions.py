"""Atomic inventory effects over the canonical stock table.

Internal service: callers must authorize the buyer/effect and own commit/rollback.
No HTTP endpoint or model tool can call this service directly. It sends no messages.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import text

RESERVATION_DDL='''CREATE TABLE IF NOT EXISTS inventory_reservation (
 tenant_id VARCHAR(128) NOT NULL, reservation_id VARCHAR(200) NOT NULL,
 sku VARCHAR(255) NOT NULL, location_id VARCHAR(200) NOT NULL, quantity INTEGER NOT NULL,
 status VARCHAR(32) NOT NULL, returned_quantity INTEGER NOT NULL DEFAULT 0,
 payload_digest VARCHAR(64) NOT NULL, expires_at TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (tenant_id,reservation_id))'''
EVENT_DDL='''CREATE TABLE IF NOT EXISTS inventory_effect_event (
 tenant_id VARCHAR(128) NOT NULL, event_id VARCHAR(200) NOT NULL,
 reservation_id VARCHAR(200) NOT NULL, kind VARCHAR(32) NOT NULL,
 quantity INTEGER NOT NULL, payload_digest VARCHAR(64) NOT NULL,
 on_hand_delta INTEGER NOT NULL, reserved_delta INTEGER NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (tenant_id,event_id))'''
MOVEMENT_DDL='''CREATE TABLE IF NOT EXISTS inventory_stock_movement (
 tenant_id VARCHAR(128) NOT NULL, source_reference VARCHAR(200) NOT NULL,
 kind VARCHAR(32) NOT NULL, sku VARCHAR(255) NOT NULL,
 source_location VARCHAR(200), destination_location VARCHAR(200) NOT NULL,
 quantity INTEGER NOT NULL, payload_digest VARCHAR(64) NOT NULL,
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY (tenant_id,source_reference))'''


def ensure_tables(db):
    for ddl in (RESERVATION_DDL,EVENT_DDL,MOVEMENT_DDL): db.execute(text(ddl))


def move_stock(db, *, tenant_id, source_reference, kind, sku, destination_location,
               quantity, source_location=None):
    """Apply an authorized receipt or complete transfer atomically.

    The calling workflow must authorize the exact document/reference. This
    primitive does not approve a purchase or infer receipt from a supplier reply.
    """
    _quantity(quantity)
    if not all(isinstance(v,str) and v.strip() for v in (tenant_id,source_reference,sku,destination_location)):
        raise ValueError('movement_identity_required')
    if kind not in ('receive','transfer'):
        raise ValueError('unsupported_stock_movement')
    if kind=='receive' and source_location is not None:
        raise ValueError('receipt_cannot_have_source_location')
    if kind=='transfer' and (not source_location or source_location==destination_location):
        raise ValueError('distinct_transfer_locations_required')
    payload=dict(tenant_id=tenant_id,source_reference=source_reference,kind=kind,sku=sku,
                 destination_location=destination_location,source_location=source_location,quantity=quantity)
    params={**payload,'payload_digest':_digest(payload)}
    with _atomic(db):
        result=db.execute(text('''INSERT INTO inventory_stock_movement
            (tenant_id,source_reference,kind,sku,destination_location,source_location,quantity,payload_digest)
            VALUES (:tenant_id,:source_reference,:kind,:sku,:destination_location,:source_location,:quantity,:payload_digest)
            ON CONFLICT(tenant_id,source_reference) DO NOTHING'''),params)
        if result.rowcount==0:
            actual=db.execute(text('''SELECT payload_digest FROM inventory_stock_movement
                WHERE tenant_id=:tenant_id AND source_reference=:source_reference'''),params).scalar_one()
            if actual!=params['payload_digest']:
                raise ValueError('stock_movement_conflict')
            return payload
        if kind=='transfer':
            if db.get_bind().dialect.name == 'postgresql':
                # Lock both legs in one stable order before either balance changes.
                # Opposite transfers otherwise each hold their source row and wait
                # for the other's destination, creating a PostgreSQL deadlock.
                locations = db.execute(text('''SELECT location_id FROM inventory_level
                    WHERE tenant_id=:tenant_id AND sku=:sku
                    AND location_id IN (:source_location,:destination_location)
                    ORDER BY location_id FOR UPDATE'''), params).scalars().all()
                if len(locations) != 2:
                    raise ValueError('stock_unavailable_or_inconsistent')
            _stock(db,dict(tenant_id=tenant_id,sku=sku,location_id=source_location),-quantity,0)
        _stock(db,dict(tenant_id=tenant_id,sku=sku,location_id=destination_location),quantity,0)
        return payload


def _quantity(value):
    if type(value) is not int or value<=0:
        raise ValueError('positive_integer_quantity_required')
    return value


def _identity(tenant_id,reservation_id):
    if not tenant_id or not reservation_id:
        raise ValueError('inventory_identity_required')
    return dict(tenant=tenant_id,reservation=reservation_id)


def _digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@contextmanager
def _atomic(db):
    # sqlite's legacy driver otherwise commits a top-level SAVEPOINT on release.
    connection=db.connection()
    if connection.dialect.name=='sqlite' and not connection.connection.driver_connection.in_transaction:
        # Reserve SQLite's writer before reading state that will be mutated.
        # A deferred read snapshot cannot safely upgrade after another writer commits.
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    with db.begin_nested():
        yield


def _row(db,params):
    suffix=' FOR UPDATE' if db.get_bind().dialect.name=='postgresql' else ''
    row=db.execute(text('SELECT * FROM inventory_reservation WHERE tenant_id=:tenant AND reservation_id=:reservation'+suffix),params).mappings().first()
    if not row: raise ValueError('reservation_not_found')
    return dict(row)


def _stock(db,row,on_hand_delta,reserved_delta):
    result=db.execute(text('''UPDATE inventory_level SET on_hand=on_hand+:oh,
      reserved=reserved+:rv,available=on_hand+:oh-reserved-:rv,updated_at=CURRENT_TIMESTAMP
      WHERE tenant_id=:tenant AND sku=:sku AND location_id=:location
      AND available=on_hand-reserved AND reserved+:rv>=0 AND on_hand+:oh>=reserved+:rv'''),
      dict(tenant=row['tenant_id'],sku=row['sku'],location=row['location_id'],oh=on_hand_delta,rv=reserved_delta))
    if result.rowcount!=1: raise ValueError('stock_unavailable_or_inconsistent')


def _event(db,params):
    result=db.execute(text('''INSERT INTO inventory_effect_event
      (tenant_id,event_id,reservation_id,kind,quantity,payload_digest,on_hand_delta,reserved_delta)
      VALUES (:tenant,:event,:reservation,:kind,:quantity,:digest,:oh,:rv)
      ON CONFLICT (tenant_id,event_id) DO NOTHING'''),params)
    if result.rowcount==1: return True
    digest=db.execute(text('SELECT payload_digest FROM inventory_effect_event WHERE tenant_id=:tenant AND event_id=:event'),params).scalar_one()
    if digest!=params['digest']: raise ValueError('inventory_event_conflict')
    return False


def _utc(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('timezone_aware_datetime_required')
    return value.astimezone(timezone.utc)


def reserve(db, *, tenant_id,reservation_id,sku,location_id,quantity,expires_at=None,now=None):
    quantity=_quantity(quantity)
    params=_identity(tenant_id,reservation_id)
    if not sku or not location_id: raise ValueError('stock_identity_required')
    params.update(sku=sku,location=location_id,quantity=quantity)
    if expires_at is not None:
        params['expires_at']=_utc(expires_at).isoformat()
    params['digest']=_digest(params)
    params.setdefault('expires_at',None)
    with _atomic(db):
        inserted=db.execute(text('''INSERT INTO inventory_reservation
          (tenant_id,reservation_id,sku,location_id,quantity,status,payload_digest,expires_at)
          VALUES (:tenant,:reservation,:sku,:location,:quantity,'reserved',:digest,:expires_at)
          ON CONFLICT (tenant_id,reservation_id) DO NOTHING'''),params)
        row=_row(db,params)
        if row['payload_digest']!=params['digest']: raise ValueError('reservation_conflict')
        if inserted.rowcount==1:
            if expires_at is not None and _utc(expires_at)<=_utc(now or datetime.now(timezone.utc)):
                raise ValueError('future_reservation_expiry_required')
            _stock(db,row,0,quantity)
            _event(db,dict(params,event='reserve:'+reservation_id,kind='reserve',oh=0,rv=quantity))
        return row


def transition(db, *, tenant_id,reservation_id,kind,event_id,quantity=None,now=None):
    params=_identity(tenant_id,reservation_id)
    if kind not in ('cancel','ship','return','expire') or not event_id:
        raise ValueError('invalid_inventory_transition')
    if kind=='return': _quantity(quantity)
    elif quantity is not None: raise ValueError('whole_reservation_transition_required')
    payload=dict(params,kind=kind,event=event_id,quantity=quantity)
    digest=_digest(payload)
    with _atomic(db):
        row=_row(db,params)
        units=quantity if kind=='return' else row['quantity']
        oh=units if kind=='return' else -units if kind=='ship' else 0
        rv=0 if kind=='return' else -units
        if not _event(db,dict(payload,quantity=units,digest=digest,oh=oh,rv=rv)):
            return row
        if kind in ('ship','expire'):
            clock=_utc(now or datetime.now(timezone.utc))
            due=bool(row['expires_at'] and _utc(datetime.fromisoformat(row['expires_at']))<=clock)
            if kind=='ship' and due: raise ValueError('reservation_expired')
            if kind=='expire' and not due: raise ValueError('reservation_not_due')
        if kind=='return':
            if row['status'] not in ('shipped','returned') or row['returned_quantity']+units>row['quantity']:
                raise ValueError('return_exceeds_shipped_quantity')
            returned=row['returned_quantity']+units
            status='returned' if returned==row['quantity'] else 'shipped'
        else:
            if row['status']!='reserved': raise ValueError('reservation_not_active')
            returned=0
            status={'ship':'shipped','cancel':'cancelled','expire':'expired'}[kind]
        _stock(db,row,oh,rv)
        db.execute(text('''UPDATE inventory_reservation SET status=:status,returned_quantity=:returned
          WHERE tenant_id=:tenant AND reservation_id=:reservation'''),dict(params,status=status,returned=returned))
        return _row(db,params)


def expire_due(db, *, tenant_id,now=None,limit=100):
    """Bounded tenant-scoped maintenance; caller owns authorization and commit.

    Shipment checks the deadline independently, even if this maintenance runs late.
    Legacy reservations without a deadline require explicit cancellation/review.
    """
    clock=_utc(now or datetime.now(timezone.utc))
    if not tenant_id or type(limit) is not int or not 1<=limit<=1000:
        raise ValueError('invalid_expiry_batch')
    with _atomic(db):
        suffix=' FOR UPDATE SKIP LOCKED' if db.get_bind().dialect.name=='postgresql' else ''
        rows=db.execute(text("SELECT reservation_id FROM inventory_reservation WHERE tenant_id=:tenant "
            "AND status='reserved' AND expires_at<=:now ORDER BY expires_at,reservation_id LIMIT :limit"+suffix),
            dict(tenant=tenant_id,now=clock.isoformat(),limit=limit)).mappings().all()
        return [transition(db,tenant_id=tenant_id,reservation_id=row['reservation_id'],kind='expire',
            event_id='expire:'+row['reservation_id'],now=clock) for row in rows]
