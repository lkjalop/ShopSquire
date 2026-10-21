"""Explicit buyer stock acceptance, using canonical case revisions and inventory effects.

Caller owns authentication, transaction commit and the authorized shop scope. This
does not send supplier messages, create a paid order or certify product suitability.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, text
from src.app.models.orm import ShoppingCaseFulfillmentSelection
from src.app.services.case_contract_binding import _owned_case
from src.app.services.inventory_transactions import _atomic, reserve, transition, expire_due
from src.app.services.shopping_case_supplier_continuation import select_fulfillment_option


def _holds(db, tenant_id, selection_id):
    return db.execute(text('SELECT * FROM inventory_reservation WHERE tenant_id=:tenant '
        'AND reservation_id LIKE :prefix ORDER BY reservation_id'),
        {'tenant':tenant_id,'prefix':'selection:'+selection_id+':%'}).mappings().all()


def _receipt(row):
    return dict(selection_id=row.selection_id,case_id=row.case_id,case_revision=row.revision,
                sku=row.preferred_sku,requested_quantity=row.requested_quantity,
                held_quantity=row.available_now,shortfall=row.requested_quantity-row.available_now,
                supplier_send='not_performed',purchase_commitment=False,
                authority='accepted_stock_hold_only')


def release_holds(db, *, tenant_id,case_id,uid,expected_revision):
    from src.app.services.shopping_case_revision import advance_material_case_revision
    with _atomic(db):
        case=_owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
        if case.revision!=expected_revision:
            raise ValueError('case_revision_conflict')
        selections=db.execute(select(ShoppingCaseFulfillmentSelection).where(
            ShoppingCaseFulfillmentSelection.tenant_id==tenant_id,
            ShoppingCaseFulfillmentSelection.case_id==case_id)).scalars().all()
        released=0
        for selection in selections:
            for hold in _holds(db,tenant_id,selection.selection_id):
                if hold['status']=='reserved':
                    transition(db,tenant_id=tenant_id,reservation_id=hold['reservation_id'],
                               kind='cancel',event_id='release:'+hold['reservation_id'])
                    released+=hold['quantity']
        if not released:
            raise ValueError('no_active_stock_holds')
        revision=advance_material_case_revision(db,tenant_id=tenant_id,case_id=case_id,
            expected_revision=expected_revision,reason='buyer_released_stock_holds')
        return dict(case_id=case_id,case_revision=revision,released_quantity=released)


def accept_request(db, *, tenant_id,case_id,uid,expected_revision,sku,quantity,idempotency_key,now=None,
                   hold_duration=timedelta(minutes=30)):
    if type(quantity) is not int or not 1<=quantity<=10000 or not sku or not idempotency_key:
        raise ValueError('invalid_stock_acceptance')
    clock=now or datetime.now(timezone.utc)
    if not isinstance(hold_duration,timedelta) or not timedelta(0)<hold_duration<=timedelta(days=1):
        raise ValueError('invalid_hold_duration')
    with _atomic(db):
        case=_owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
        previous=db.execute(select(ShoppingCaseFulfillmentSelection).where(
            ShoppingCaseFulfillmentSelection.tenant_id==tenant_id,
            ShoppingCaseFulfillmentSelection.case_id==case_id,
        ).order_by(ShoppingCaseFulfillmentSelection.revision.desc())).scalars().all()
        replay=next((r for r in previous if r.selection_idempotency_key==idempotency_key),None)
        if replay:
            if (replay.uid,replay.preferred_sku,replay.requested_quantity,replay.revision)!=(uid,sku,quantity,expected_revision+1):
                raise ValueError('stock_acceptance_replay_conflict')
            if case.revision!=replay.revision:
                raise ValueError('stock_acceptance_revision_superseded')
            _,error=select_fulfillment_option(db,tenant_id=tenant_id,case_id=case_id,uid=uid,
                expected_revision=expected_revision,choice='split_delivery',preferred_sku=sku,
                requested_quantity=quantity,available_now=replay.available_now,idempotency_key=idempotency_key,
                offers=[],use_canonical_case_revision=True,commit=False)
            if error:
                raise ValueError(error)
            return _receipt(replay)
        if case.revision!=expected_revision:
            raise ValueError('case_revision_conflict')
        expire_due(db,tenant_id=tenant_id,now=clock)
        for old in previous:
            for hold in _holds(db,tenant_id,old.selection_id):
                if hold['status'] in ('shipped','returned'):
                    raise ValueError('dispatched_stock_requires_operator_recovery')
                if hold['status']=='reserved':
                    transition(db,tenant_id=tenant_id,reservation_id=hold['reservation_id'],
                               kind='cancel',event_id='amend:'+hold['reservation_id'])
        locations=db.execute(text('SELECT location_id,available FROM inventory_level '
            'WHERE tenant_id=:tenant AND sku=:sku ORDER BY location_id'),{'tenant':tenant_id,'sku':sku}).all()
        if not locations:
            raise ValueError('stock_identity_not_found')
        available=min(quantity,sum(max(0,r.available) for r in locations))
        selection,error=select_fulfillment_option(db,tenant_id=tenant_id,case_id=case_id,uid=uid,
            expected_revision=expected_revision,choice='split_delivery',preferred_sku=sku,
            requested_quantity=quantity,available_now=available,idempotency_key=idempotency_key,
            offers=[],use_canonical_case_revision=True,commit=False)
        if error:
            raise ValueError(error)
        remaining=available
        for location in locations:
            units=min(remaining,max(0,location.available))
            if units:
                identity='selection:'+selection.selection_id+':'+hashlib.sha256(location.location_id.encode()).hexdigest()[:16]
                reserve(db,tenant_id=tenant_id,reservation_id=identity,sku=sku,
                        location_id=location.location_id,quantity=units,expires_at=clock+hold_duration,now=clock)
                remaining-=units
        row=db.get(ShoppingCaseFulfillmentSelection,selection.selection_id)
        return _receipt(row)
