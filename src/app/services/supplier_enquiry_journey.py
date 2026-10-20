"""Case-bound enquiry/review orchestration; caller controls identity and commit.

No supplier prose grants authority. The demo adapter resolves fictional contacts;
this service uses the existing person permits, outbox and injected transport.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from src.app.services.fulfillment import person_approval as approval, outbound_queue as queue
from src.app.services.fulfillment.effect_contract import effect_digest
from src.app.services.inventory_transactions import _atomic

ENQUIRY_DDL='''CREATE TABLE IF NOT EXISTS supplier_enquiry_request (
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,case_id TEXT NOT NULL,case_revision INTEGER NOT NULL,
 requester_principal TEXT NOT NULL,supplier_ref TEXT NOT NULL,recipient TEXT NOT NULL,
 source_reference TEXT NOT NULL,sku TEXT NOT NULL,requested_quantity INTEGER NOT NULL,
 shortfall INTEGER NOT NULL,value_cents INTEGER NOT NULL,currency TEXT NOT NULL,
 status TEXT NOT NULL,approval_id TEXT,created_at TEXT NOT NULL,
 UNIQUE(tenant_id,source_reference))'''
REPLY_DDL='''CREATE TABLE IF NOT EXISTS supplier_enquiry_reply (
 id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,enquiry_id TEXT NOT NULL,message_id TEXT NOT NULL,
 sender_ref TEXT NOT NULL,terms_json TEXT NOT NULL,payload_digest TEXT NOT NULL,
 status TEXT NOT NULL,reason TEXT NOT NULL,reviewer_principal TEXT,received_at TEXT NOT NULL,
 UNIQUE(tenant_id,message_id))'''


class QuoteTerms(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    sku: str=Field(min_length=1,max_length=200)
    quantity: int=Field(ge=0,le=10000)
    unit_cost_cents: int=Field(ge=0,le=100000000)
    freight_cents: int=Field(ge=0,le=100000000)
    currency: str=Field(pattern='^[A-Z]{3}$')
    lead_days: int=Field(ge=0,le=365)
    minimum_order: int=Field(ge=1,le=10000)
    expires_at: str=Field(max_length=80)


def ensure_tables(db):
    for ddl in (ENQUIRY_DDL,REPLY_DDL,approval.CASE_BINDING_DDL):db.execute(text(ddl))


def _now(now=None):return now or datetime.now(timezone.utc)


def _expiry(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('quote_timezone_required')
    return stamp


def get(db, *, tenant_id,enquiry_id):
    row=db.execute(text('SELECT * FROM supplier_enquiry_request WHERE tenant_id=:tenant AND id=:id'),dict(tenant=tenant_id,id=enquiry_id)).mappings().first()
    if not row:raise ValueError('enquiry_not_found')
    return dict(row)


def _current(db,row,now=None):
    revision=db.execute(text('SELECT revision FROM shopping_cases WHERE tenant_id=:tenant AND case_id=:case'),
        dict(tenant=row['tenant_id'],case=row['case_id'])).scalar()
    if revision!=row['case_revision']:raise ValueError('enquiry_case_revision_stale')
    selection = db.execute(text('SELECT preferred_sku,requested_quantity FROM shopping_case_fulfillment_selections '
        'WHERE tenant_id=:tenant AND case_id=:case AND revision=:revision'),
        dict(tenant=row['tenant_id'], case=row['case_id'], revision=revision)).first()
    if not selection or tuple(selection) != (row['sku'], row['requested_quantity']):
        raise ValueError('enquiry_selection_stale')
    if remaining_shortfall(db,tenant_id=row['tenant_id'],case_id=row['case_id'],revision=revision,now=now)!=row['shortfall']:
        raise ValueError('enquiry_shortfall_stale')


from src.app.services.shortfall_enquiry_preview import remaining_shortfall


def create(db, *, tenant_id,case_id,expected_revision,requester_principal,supplier_ref,source_reference,recipient_resolver,now=None):
    approval._person(db,tenant_id,requester_principal)
    # A trusted deployment adapter resolves contacts; buyer prose never does.
    recipient=recipient_resolver(supplier_ref)
    if not isinstance(recipient,str) or not recipient.strip():raise ValueError('supplier_contact_required')
    clock=_now(now)
    selection=db.execute(text('''SELECT s.* FROM shopping_case_fulfillment_selections s
        JOIN shopping_cases c ON c.case_id=s.case_id AND c.tenant_id=s.tenant_id AND c.revision=s.revision
        WHERE s.tenant_id=:tenant AND s.case_id=:case AND s.revision=:revision'''),
        dict(tenant=tenant_id,case=case_id,revision=expected_revision)).mappings().first()
    if not selection:raise ValueError('current_accepted_selection_required')
    shortfall=remaining_shortfall(db,tenant_id=tenant_id,case_id=case_id,revision=expected_revision,now=clock)
    if not shortfall:raise ValueError('no_stock_shortfall')
    product=db.execute(text('SELECT price_cents,currency FROM products WHERE sku=:sku'),{'sku':selection['preferred_sku']}).first()
    if not product or type(product[0]) is not int or product[0]<0:raise ValueError('server_valuation_required')
    row=dict(id=str(uuid.uuid4()),tenant_id=tenant_id,case_id=case_id,case_revision=expected_revision,
        requester_principal=requester_principal,supplier_ref=supplier_ref,recipient=recipient,source_reference=source_reference,
        sku=selection['preferred_sku'],requested_quantity=selection['requested_quantity'],shortfall=shortfall,
        value_cents=selection['requested_quantity']*product[0],currency=product[1],status='pending',created_at=clock.isoformat())
    previous=db.execute(text('SELECT * FROM supplier_enquiry_request WHERE tenant_id=:tenant_id AND source_reference=:source_reference'),row).mappings().first()
    if previous:
        if any(previous[key]!=row[key] for key in row if key not in ('id','status','created_at')):raise ValueError('enquiry_replay_conflict')
        return dict(previous)
    db.execute(text('INSERT INTO supplier_enquiry_request ('+','.join(row)+') VALUES ('+','.join(':'+key for key in row)+')'),row)
    return get(db,tenant_id=tenant_id,enquiry_id=row['id'])


def _effect(row,actor):
    return dict(tenant_id=row['tenant_id'],case_id=row['case_id'],recipient=row['recipient'],
        subject='Stock shortfall enquiry',
        body=f"Please quote {row['shortfall']} units of {row['sku']} for case revision {row['case_revision']}. No purchase is authorized.",
        channel='email',actor_type='human_operator',actor_id=actor,transition_event='external_message_sent',
        idempotency_key='supplier-enquiry:'+row['id'])


def approve(db, *, tenant_id,enquiry_id,approver_principal,now=None):
    with _atomic(db):
        row=get(db,tenant_id=tenant_id,enquiry_id=enquiry_id);_current(db,row,now)
        if row['status']!='pending':raise ValueError('enquiry_not_pending')
        clock=_now(now)
        grant=approval.issue(db,requester_principal=row['requester_principal'],approver_principal=approver_principal,
            effect=_effect(row,approver_principal),value_cents=row['value_cents'],expires_at=clock+timedelta(hours=1),now=clock)
        approval.bind_case(db,tenant_id=tenant_id,approval_id=grant['id'],case_id=row['case_id'],case_revision=row['case_revision'])
        changed=db.execute(text("UPDATE supplier_enquiry_request SET status='approved',approval_id=:grant WHERE tenant_id=:tenant AND id=:id AND status='pending'"),
            dict(grant=grant['id'],tenant=tenant_id,id=enquiry_id))
        if changed.rowcount!=1:raise ValueError('enquiry_approval_conflict')
        return get(db,tenant_id=tenant_id,enquiry_id=enquiry_id)


def dispatch(db, *, tenant_id,enquiry_id,transport,now=None):
    row=get(db,tenant_id=tenant_id,enquiry_id=enquiry_id);_current(db,row,now)
    if row['status']!='approved' or not row['approval_id']:raise ValueError('approved_enquiry_required')
    grant=db.execute(text('SELECT approver_principal FROM person_effect_approval WHERE tenant_id=:tenant AND id=:id'),
        dict(tenant=tenant_id,id=row['approval_id'])).first()
    if not grant:raise ValueError('person_approval_required')
    effect=_effect(row,grant[0])
    approval.validate(db,tenant_id=tenant_id,approval_id=row['approval_id'],
        digest=effect_digest(**effect,person_approval_id=row['approval_id']),now=_now(now))
    receipt=queue.enqueue(db,**effect,person_approval_id=row['approval_id'],now_iso=_now(now).isoformat())
    if not receipt.get('message_id') or receipt['status']=='effect_conflict':raise ValueError('outbox_enqueue_failed')
    queue.process_pending(db,tenant_id=tenant_id,transport=transport,only_key=effect['idempotency_key'],now_iso=_now(now).isoformat())
    return view(db,tenant_id=tenant_id,enquiry_id=enquiry_id,now=now)


def _reason(db,row,sender,terms,now):
    if sender!=row['supplier_ref']:return 'sender_mismatch'
    try:_current(db,row,now)
    except ValueError as exc:
        return {'enquiry_shortfall_stale': 'stale_shortfall',
                'enquiry_selection_stale': 'stale_selection'}.get(str(exc), 'stale_case_revision')
    if _expiry(terms['expires_at'])<=now:return 'quote_expired'
    if terms['currency']!=row['currency']:return 'currency_mismatch'
    return ''


def receive(db, *, tenant_id,enquiry_id,message_id,sender_ref,terms,now=None):
    row=get(db,tenant_id=tenant_id,enquiry_id=enquiry_id)
    terms=QuoteTerms.model_validate(terms).model_dump();_expiry(terms['expires_at'])
    message=queue.get_by_key(db,tenant_id=tenant_id,idempotency_key='supplier-enquiry:'+enquiry_id)
    if not message or message['status']!='sent':raise ValueError('sent_enquiry_required')
    content=dict(enquiry_id=enquiry_id,sender_ref=sender_ref,terms=terms)
    digest=hashlib.sha256(json.dumps(content,sort_keys=True).encode()).hexdigest()
    previous=db.execute(text('SELECT * FROM supplier_enquiry_reply WHERE tenant_id=:tenant AND message_id=:message'),
        dict(tenant=tenant_id,message=message_id)).mappings().first()
    if previous:
        if previous['payload_digest']!=digest:raise ValueError('supplier_reply_conflict')
        return dict(previous)
    reason=_reason(db,row,sender_ref,terms,_now(now))
    result=dict(id=str(uuid.uuid4()),tenant_id=tenant_id,enquiry_id=enquiry_id,message_id=message_id,
        sender_ref=sender_ref,terms_json=json.dumps(terms,sort_keys=True),payload_digest=digest,
        status='quarantined' if reason else 'review_required',reason=reason,received_at=_now(now).isoformat())
    db.execute(text('INSERT INTO supplier_enquiry_reply ('+','.join(result)+') VALUES ('+','.join(':'+key for key in result)+')'),result)
    return result


def review(db, *, tenant_id,enquiry_id,reply_id,reviewer_principal,now=None):
    approval._person(db,tenant_id,reviewer_principal)
    row=get(db,tenant_id=tenant_id,enquiry_id=enquiry_id)
    reply=db.execute(text('SELECT * FROM supplier_enquiry_reply WHERE tenant_id=:tenant AND enquiry_id=:enquiry AND id=:id'),
        dict(tenant=tenant_id,enquiry=enquiry_id,id=reply_id)).mappings().first()
    if not reply:raise ValueError('supplier_reply_not_found')
    if reply['status']=='quarantined' or _reason(db,row,reply['sender_ref'],json.loads(reply['terms_json']),_now(now)):
        raise ValueError('current_verified_reply_required')
    db.execute(text("UPDATE supplier_enquiry_reply SET status='reviewed',reviewer_principal=:actor WHERE tenant_id=:tenant AND id=:id"),
        dict(actor=reviewer_principal,tenant=tenant_id,id=reply_id))
    return dict(reply,status='reviewed',reviewer_principal=reviewer_principal)


def view(db, *, tenant_id,enquiry_id,now=None):
    row=get(db,tenant_id=tenant_id,enquiry_id=enquiry_id)
    grant=db.execute(text('SELECT revoked_at,expires_at FROM person_effect_approval WHERE tenant_id=:tenant AND id=:id'),
        dict(tenant=tenant_id,id=row['approval_id'])).mappings().first() if row['approval_id'] else None
    approval_state=('not_requested' if not grant else 'revoked' if grant['revoked_at'] else
        'expired' if approval._time(grant['expires_at'])<=_now(now) else 'current')
    if approval_state == 'current':
        actor = db.execute(text('SELECT approver_principal FROM person_effect_approval WHERE tenant_id=:tenant AND id=:id'),
                           dict(tenant=tenant_id, id=row['approval_id'])).scalar_one()
        try:
            approval.validate(db, tenant_id=tenant_id, approval_id=row['approval_id'],
                digest=effect_digest(**_effect(row, actor), person_approval_id=row['approval_id']), now=_now(now))
        except ValueError:
            approval_state = 'invalid'
    message=queue.get_by_key(db,tenant_id=tenant_id,idempotency_key='supplier-enquiry:'+enquiry_id)
    quotes=[]
    for reply in db.execute(text('SELECT * FROM supplier_enquiry_reply WHERE tenant_id=:tenant AND enquiry_id=:id ORDER BY received_at,id'),
        dict(tenant=tenant_id,id=enquiry_id)).mappings().all():
        terms=json.loads(reply['terms_json']);reason=_reason(db,row,reply['sender_ref'],terms,_now(now))
        eligible=reply['status']=='reviewed' and not reason
        quantity=min(row['shortfall'],terms['quantity'])
        coverage=('substitute_unverified' if terms['sku']!=row['sku'] else 'declined' if not terms['quantity'] else
            'below_minimum' if quantity<terms['minimum_order'] else 'partial' if quantity<row['shortfall'] else 'full')
        eligible=eligible and coverage in ('partial','full')
        quotes.append(dict(id=reply['id'],status=reply['status'],reason=reason or reply['reason'],terms=terms,
            assessment=dict(eligible=eligible,coverage=coverage,
                landed_cost_cents=quantity*terms['unit_cost_cents']+terms['freight_cents'] if eligible and coverage in ('partial','full') else None,
                sourced_quantity=quantity,delivery_days=terms['lead_days'],commerce_authority='none')))
    effect = _effect(row, 'preview')
    reviewed_message = {key: effect[key] for key in ('recipient', 'subject', 'body')}
    return dict(row,message=reviewed_message,approval_state=approval_state,delivery_status=message['status'] if message else 'not_dispatched',
        transport_attempts=message['attempts'] if message else 0,
        reply_status='replies_received' if quotes else 'awaiting_reply',quotes=quotes,commerce_authority='none',simulation_only=True)
