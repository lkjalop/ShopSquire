"""Evidence-bound upgrade/cross-sell offers. Product facts remain in observations.

An offer is advisory until an explicit buyer acceptance. Acceptance revalidates
evidence, price, scope and cart version in the same transaction as the cart edit.
"""
from datetime import datetime,timezone,timedelta
import hashlib
import json
import uuid
from sqlalchemy import select,text,inspect
from src.app.models.orm import Product,ProductConfiguration,ProductEvidenceObservation
from src.app.services.case_contract_binding import _owned_case
from src.app.services.inventory_transactions import _atomic
from src.app.services.shopping_case_revision import advance_material_case_revision

DDL='''CREATE TABLE IF NOT EXISTS governed_product_offer (
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,case_id TEXT NOT NULL,uid TEXT NOT NULL,
 case_revision INTEGER NOT NULL,cart_id TEXT NOT NULL,cart_version INTEGER NOT NULL,
 input_json TEXT NOT NULL,projection_json TEXT NOT NULL,projection_digest TEXT NOT NULL,
 expires_at TEXT NOT NULL,status TEXT NOT NULL,result_json TEXT)'''


def _time(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp


def _hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def evaluate(db, *, tenant_id,base_configuration_id,target_configuration_id,need,quantity,now):
    if type(quantity) is not int or not 1<=quantity<=10000:raise ValueError('offer_quantity_invalid')
    if base_configuration_id==target_configuration_id:raise ValueError('distinct_configurations_required')
    base=db.get(ProductConfiguration,base_configuration_id);target=db.get(ProductConfiguration,target_configuration_id)
    catalog={}
    for config in (base,target):
        if not config or config.tenant_id!=tenant_id or not config.active:raise ValueError('scoped_configuration_required')
        if not config.price_observed_at or not timedelta(0)<=now-_time(config.price_observed_at)<=timedelta(days=1):
            raise ValueError('current_configuration_price_required')
        if type(config.price_cents) is not int or config.price_cents<0:raise ValueError('configuration_price_invalid')
        product=db.execute(select(Product).where(Product.sku==config.sku)).scalar_one_or_none()
        if not product or not product.active or (product.price_cents,product.currency)!=(config.price_cents,config.currency):
            raise ValueError('configuration_catalogue_price_mismatch')
        catalog[config.sku]=product
    if base.currency!=target.currency:raise ValueError('offer_currency_mismatch')
    candidates=db.execute(select(ProductEvidenceObservation).where(
        ProductEvidenceObservation.configuration_id==base_configuration_id,
        ProductEvidenceObservation.attribute_key=='supported_product_relation')).scalars().all()
    facts=[fact for fact in candidates if isinstance(fact.value_json,dict)
        and fact.value_json.get('target_configuration_id')==target_configuration_id and fact.value_json.get('need')==need]
    # Unknown, conflicting or revoked observations must never imply compatibility.
    if len(facts)!=1:raise ValueError('unambiguous_relationship_evidence_required')
    fact=facts[0];value=fact.value_json
    if (fact.claim_class!='attested' or fact.evidence_status!='observed' or fact.conflict_group
        or not fact.source_id or not fact.source_record_id or not fact.source_excerpt
        or not fact.observed_at or not fact.expires_at or not _time(fact.observed_at)<=now<_time(fact.expires_at)
        or value.get('supported') is not True or value.get('kind') not in ('upgrade','cross_sell')
        or not isinstance(value.get('benefit'),str) or not value['benefit'].strip()
        or value['benefit'] not in fact.source_excerpt):
        raise ValueError('current_supported_relationship_required')
    kind=value['kind']
    if kind=='upgrade' and target.price_cents<=base.price_cents:raise ValueError('upgrade_price_increment_required')
    configurations=[base,target] if kind=='cross_sell' else [target]
    lines=[]
    for config in configurations:
        available=db.execute(text('SELECT COALESCE(SUM(available),0) FROM inventory_level WHERE tenant_id=:tenant AND sku=:sku'),
            dict(tenant=tenant_id,sku=config.sku)).scalar_one()
        if available<quantity:raise ValueError('offer_stock_unavailable')
        lines.append(dict(sku=config.sku,quantity=quantity,unit_price_cents=config.price_cents,configuration_id=config.id))
    from src.app.services.bundle_pricing import evaluate_bundle_savings
    pricing=evaluate_bundle_savings([dict(sku=line['sku'],quantity=line['quantity'],price_cents=line['unit_price_cents'],
        name=catalog[line['sku']].name,specs=catalog[line['sku']].specs or {}) for line in lines])
    total=pricing['final_total_cents']
    return dict(kind=kind,need=need,benefit=value['benefit'],currency=base.currency,base_total_cents=quantity*base.price_cents,
        incremental_cents=total-quantity*base.price_cents,total_cents=total,lines=lines,
        applied_discount_cents=pricing['applied_discount_cents'],discount_approval_required=pricing.get('approval_required',False),
        evidence=dict(id=fact.id,source_id=fact.source_id,source_record_id=fact.source_record_id,
            excerpt=fact.source_excerpt,observed_at=_time(fact.observed_at).isoformat(),expires_at=_time(fact.expires_at).isoformat()),
        configuration_hashes=[base.configuration_hash,target.configuration_hash],commerce_authority='none')


def _cart(db,tenant,uid,cart_id):
    row=db.execute(text("SELECT line_items,version FROM draft_orders WHERE id=:id AND tenant_id=:tenant AND customer_id=:uid AND status='draft'"),
        dict(id=cart_id,tenant=tenant,uid=uid)).first()
    if not row:raise ValueError('scoped_draft_cart_required')
    return row


def _no_active_holds(db,tenant,case_id):
    if inspect(db.connection()).has_table('shopping_case_fulfillment_selections') and inspect(db.connection()).has_table('inventory_reservation'):
        held=db.execute(text("SELECT 1 FROM inventory_reservation r JOIN shopping_case_fulfillment_selections s "
            "ON s.tenant_id=r.tenant_id AND r.reservation_id LIKE 'selection:' || s.selection_id || ':%' "
            "WHERE s.tenant_id=:tenant AND s.case_id=:case AND r.status IN ('reserved','shipped','returned') LIMIT 1"),
            dict(tenant=tenant,case=case_id)).first()
        if held:raise ValueError('resolve_existing_fulfillment_before_product_change')


def propose(db, *, tenant_id,case_id,uid,expected_revision,cart_id,base_configuration_id,target_configuration_id,need,quantity,now=None):
    clock=now or datetime.now(timezone.utc)
    case=_owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
    if case.revision!=expected_revision:raise ValueError('case_revision_conflict')
    _no_active_holds(db,tenant_id,case_id)
    cart=_cart(db,tenant_id,uid,cart_id)
    inputs=dict(tenant_id=tenant_id,base_configuration_id=base_configuration_id,target_configuration_id=target_configuration_id,need=need,quantity=quantity)
    projection=evaluate(db,**inputs,now=clock)
    existing=json.loads(cart[0]) if isinstance(cart[0],str) else cart[0]
    base=db.get(ProductConfiguration,base_configuration_id)
    if existing and (len(existing)!=1 or existing[0].get('sku')!=base.sku or existing[0].get('quantity')!=quantity):
        raise ValueError('offer_requires_empty_or_exact_base_cart')
    row=dict(id=str(uuid.uuid4()),tenant_id=tenant_id,case_id=case_id,uid=uid,case_revision=expected_revision,
        cart_id=cart_id,cart_version=cart[1],input_json=json.dumps(inputs,sort_keys=True),projection_json=json.dumps(projection,sort_keys=True),
        projection_digest=_hash(projection),expires_at=(clock+timedelta(minutes=15)).isoformat(),status='proposed')
    db.execute(text("UPDATE governed_product_offer SET status='superseded' WHERE tenant_id=:tenant_id AND case_id=:case_id AND uid=:uid AND status='proposed'"),row)
    db.execute(text('INSERT INTO governed_product_offer ('+','.join(row)+') VALUES ('+','.join(':'+key for key in row)+')'),row)
    return dict(projection,id=row['id'],status='proposed',expires_at=row['expires_at'])


def decline(db, *, tenant_id,case_id,uid,offer_id):
    _owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
    changed=db.execute(text("UPDATE governed_product_offer SET status='declined' WHERE tenant_id=:tenant AND case_id=:case AND uid=:uid AND id=:id AND status='proposed'"),
        dict(tenant=tenant_id,case=case_id,uid=uid,id=offer_id))
    if changed.rowcount!=1:raise ValueError('proposed_offer_required')
    return dict(status='declined',offer_id=offer_id)


def accept(db, *, tenant_id,case_id,uid,offer_id,now=None):
    clock=now or datetime.now(timezone.utc)
    with _atomic(db):
        row=db.execute(text('SELECT * FROM governed_product_offer WHERE tenant_id=:tenant AND case_id=:case AND uid=:uid AND id=:id'),
            dict(tenant=tenant_id,case=case_id,uid=uid,id=offer_id)).mappings().first()
        if not row:raise ValueError('offer_not_found')
        case=_owned_case(db,tenant_id=tenant_id,case_id=case_id,uid=uid)
        if row['status']=='accepted':return json.loads(row['result_json'])
        if row['status']!='proposed' or not clock<_time(row['expires_at']):raise ValueError('offer_not_current')
        if case.revision!=row['case_revision']:raise ValueError('case_revision_conflict')
        _no_active_holds(db,tenant_id,case_id)
        cart=_cart(db,tenant_id,uid,row['cart_id'])
        if cart[1]!=row['cart_version']:raise ValueError('cart_version_conflict')
        projection=evaluate(db,**json.loads(row['input_json']),now=clock)
        if _hash(projection)!=row['projection_digest']:raise ValueError('offer_evidence_or_price_changed')
        lines=[dict(sku=line['sku'],quantity=line['quantity'],added_at=clock.strftime('%Y-%m-%d %H:%M:%S')) for line in projection['lines']]
        from src.app.routers.cart import _save_cart_versioned
        if not _save_cart_versioned(db,row['cart_id'],lines,row['cart_version']):raise ValueError('cart_version_conflict')
        revision=advance_material_case_revision(db,tenant_id=tenant_id,case_id=case_id,expected_revision=row['case_revision'],reason='buyer_accepted_product_offer')
        result=dict(status='accepted',offer_id=offer_id,case_revision=revision,cart_id=row['cart_id'],
            total_cents=projection['total_cents'],currency=projection['currency'],lines=projection['lines'],purchase_authority='none')
        db.execute(text("UPDATE governed_product_offer SET status='accepted',result_json=:result WHERE id=:id AND status='proposed'"),
            dict(id=offer_id,result=json.dumps(result,sort_keys=True)))
        return result
