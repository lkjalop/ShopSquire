"""Independent-person permits for exact outbound effects.

Internal boundary: principal hashes must come from authenticated request identities.
Person enrollment is an administrator-owned identity assertion, never a model field.
This does not enable real transports or turn a shared key into a verified person.
"""
from datetime import datetime,timezone
import json
import uuid
from sqlalchemy import text, inspect
from src.app.services.fulfillment.effect_contract import effect_digest
from src.app.services.fulfillment.approval_policy import approver_can_clear

PERSON_DDL='''CREATE TABLE IF NOT EXISTS operator_person_binding (
 tenant_id VARCHAR(128) NOT NULL, principal_hash VARCHAR(64) NOT NULL,
 person_id VARCHAR(200) NOT NULL, assigned_by VARCHAR(200) NOT NULL,
 status VARCHAR(32) NOT NULL DEFAULT 'active',PRIMARY KEY (tenant_id,principal_hash))'''
GRANT_DDL='''CREATE TABLE IF NOT EXISTS person_effect_approval (
 id VARCHAR(64) PRIMARY KEY,tenant_id VARCHAR(128) NOT NULL,
 requester_principal VARCHAR(64) NOT NULL,approver_principal VARCHAR(64) NOT NULL,
 requester_person VARCHAR(200) NOT NULL,approver_person VARCHAR(200) NOT NULL,
 value_cents INTEGER NOT NULL,effect_digest VARCHAR(64) NOT NULL,effect_json TEXT NOT NULL,
 issued_at TEXT NOT NULL,expires_at TEXT NOT NULL,revoked_at TEXT,revoked_by TEXT)'''

CASE_BINDING_DDL='''CREATE TABLE IF NOT EXISTS person_effect_case_binding (
 tenant_id TEXT NOT NULL,approval_id TEXT NOT NULL,case_id TEXT NOT NULL,case_revision INTEGER NOT NULL,
 PRIMARY KEY(tenant_id,approval_id))'''


def bind_case(db, *, tenant_id,approval_id,case_id,case_revision):
    db.execute(text('INSERT INTO person_effect_case_binding (tenant_id,approval_id,case_id,case_revision) '
        'VALUES (:tenant,:approval,:case,:revision)'),
        dict(tenant=tenant_id,approval=approval_id,case=case_id,revision=case_revision))


def ensure_tables(db):
    for ddl in (PERSON_DDL,GRANT_DDL):db.execute(text(ddl))


def bind_person(db, *, tenant_id,principal_hash,person_id,assigned_by):
    if not all((tenant_id,principal_hash,person_id,assigned_by)):
        raise ValueError('person_binding_fields_required')
    params=dict(tenant=tenant_id,principal=principal_hash,person=person_id,actor=assigned_by)
    db.execute(text('''INSERT INTO operator_person_binding (tenant_id,principal_hash,person_id,assigned_by)
      VALUES (:tenant,:principal,:person,:actor) ON CONFLICT (tenant_id,principal_hash) DO NOTHING'''),params)
    actual=db.execute(text('SELECT person_id FROM operator_person_binding WHERE tenant_id=:tenant AND principal_hash=:principal'),params).scalar_one()
    if actual!=person_id:raise ValueError('person_binding_conflict')


def _person(db,tenant,principal):
    row=db.execute(text('''SELECT p.person_id,m.role FROM operator_person_binding p
      JOIN operator_tenant_membership m ON m.tenant_id=p.tenant_id AND m.principal_hash=p.principal_hash
      WHERE p.tenant_id=:tenant AND p.principal_hash=:principal AND p.status='active' AND m.status='active' '''),
      dict(tenant=tenant,principal=principal)).first()
    if not row or not row[0]:raise ValueError('active_person_membership_required')
    return row


def _people(db,tenant,requester,approver,value):
    first=_person(db,tenant,requester)
    second=_person(db,tenant,approver)
    if first[0]==second[0]:raise ValueError('distinct_people_required')
    if not approver_can_clear(second[1],value)['ok']:raise ValueError('approval_tier_insufficient')
    return first[0],second[0]


def _time(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00')) if isinstance(value,str) else value
    return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)


def issue(db, *, requester_principal,approver_principal,effect,value_cents,expires_at,now=None,
          digest_builder=effect_digest):
    now=_time(now or datetime.now(timezone.utc))
    end=_time(expires_at)
    if not 0<(end-now).total_seconds()<=86400:raise ValueError('approval_expiry_invalid')
    if type(value_cents) is not int or value_cents<0:raise ValueError('approval_spend_invalid')
    tenant=effect['tenant_id']
    if effect.get('actor_id')!=approver_principal:raise ValueError('effect_approver_mismatch')
    first,second=_people(db,tenant,requester_principal,approver_principal,value_cents)
    identity=str(uuid.uuid4())
    digest=digest_builder(**effect,person_approval_id=identity)
    row=dict(id=identity,tenant_id=tenant,requester_principal=requester_principal,approver_principal=approver_principal,
        requester_person=first,approver_person=second,value_cents=value_cents,effect_digest=digest,
        effect_json=json.dumps(effect,sort_keys=True),issued_at=now.isoformat(),expires_at=end.isoformat())
    db.execute(text('''INSERT INTO person_effect_approval (id,tenant_id,requester_principal,approver_principal,
      requester_person,approver_person,value_cents,effect_digest,effect_json,issued_at,expires_at)
      VALUES (:id,:tenant_id,:requester_principal,:approver_principal,:requester_person,:approver_person,
      :value_cents,:effect_digest,:effect_json,:issued_at,:expires_at)'''),row)
    return row


def validate(db, *, tenant_id,approval_id,digest,now=None):
    row=db.execute(text('SELECT * FROM person_effect_approval WHERE tenant_id=:tenant AND id=:id'),
        {'tenant':tenant_id,'id':approval_id}).mappings().first()
    if not row or row['effect_digest']!=digest:raise ValueError('person_approval_effect_mismatch')
    now=_time(now or datetime.now(timezone.utc))
    if row['revoked_at'] or not _time(row['issued_at'])<=now<_time(row['expires_at']):
        raise ValueError('person_approval_not_current')
    people=_people(db,tenant_id,row['requester_principal'],row['approver_principal'],row['value_cents'])
    if people!=(row['requester_person'],row['approver_person']):raise ValueError('person_binding_changed')
    if inspect(db.connection()).has_table('person_effect_case_binding'):
        binding=db.execute(text('SELECT case_id,case_revision FROM person_effect_case_binding WHERE tenant_id=:tenant AND approval_id=:id'),
            dict(tenant=tenant_id,id=approval_id)).first()
        if binding:
            revision=db.execute(text('SELECT revision FROM shopping_cases WHERE tenant_id=:tenant AND case_id=:case'),
                dict(tenant=tenant_id,case=binding[0])).scalar()
            if revision!=binding[1]:raise ValueError('person_approval_case_revision_stale')
    # Workflow preconditions are rechecked by both enqueue and the actual worker.
    # Exact payload approval alone cannot establish current inventory demand.
    if inspect(db.connection()).has_table('supplier_enquiry_request'):
        enquiry=db.execute(text('SELECT * FROM supplier_enquiry_request WHERE tenant_id=:tenant AND approval_id=:id'),
            dict(tenant=tenant_id,id=approval_id)).mappings().first()
        if enquiry:
            from src.app.services.supplier_enquiry_journey import _current
            _current(db,enquiry,now)
    return dict(row)


def revoke(db, *, tenant_id,approval_id,revoked_by,now=None):
    if not revoked_by:raise ValueError('revoker_required')
    result=db.execute(text('''UPDATE person_effect_approval SET revoked_at=:now,revoked_by=:actor
      WHERE tenant_id=:tenant AND id=:id AND revoked_at IS NULL'''),
      dict(tenant=tenant_id,id=approval_id,actor=revoked_by,now=_time(now or datetime.now(timezone.utc)).isoformat()))
    return result.rowcount==1


def dispatch_current(db,tenant,approval_id,digest,now):
    if not approval_id:return True  # legacy contained messages; real transport remains disabled
    try:
        validate(db,tenant_id=tenant,approval_id=approval_id,digest=digest,now=now)
        return True
    except Exception:
        return False
