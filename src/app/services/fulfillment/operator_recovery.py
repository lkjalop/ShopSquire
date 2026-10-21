"""Record operator observations of uncertain sends; never authorize another send.

Internal service. The caller supplies an authenticated principal, owns the transaction,
and must retain the referenced provider evidence. An observation is not supplier acknowledgement.
"""
import hashlib
import json
from sqlalchemy import text
from src.app.services.fulfillment.person_approval import _person
from src.app.services.inventory_transactions import _atomic

DDL = '''CREATE TABLE IF NOT EXISTS outbound_recovery_observation (
 tenant_id VARCHAR(128) NOT NULL, message_id VARCHAR(200) NOT NULL,
 operator_principal VARCHAR(64) NOT NULL, outcome VARCHAR(32) NOT NULL,
 evidence_ref TEXT NOT NULL, provider_ref TEXT NOT NULL, payload_digest VARCHAR(64) NOT NULL,
 observed_at TEXT NOT NULL, PRIMARY KEY (tenant_id,message_id))'''


def ensure_tables(db):
    db.execute(text(DDL))


def resolve(db, *, tenant_id, message_id, operator_principal, outcome, evidence_ref,
            provider_ref='', now):
    if outcome not in {'submitted', 'not_delivered'} or not str(evidence_ref).strip():
        raise ValueError('provider_observation_required')
    if outcome == 'submitted' and not str(provider_ref).strip():
        raise ValueError('provider_reference_required')
    if outcome == 'not_delivered' and provider_ref:
        raise ValueError('contradictory_provider_reference')
    payload = dict(tenant_id=tenant_id, message_id=message_id, operator_principal=operator_principal,
                   outcome=outcome, evidence_ref=evidence_ref, provider_ref=provider_ref)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    params = {**payload, 'digest': digest, 'now': now.isoformat(),
              'status': 'sent' if outcome == 'submitted' else 'resolved_not_delivered'}
    with _atomic(db):
        _, role = _person(db, tenant_id, operator_principal)
        if role not in {'owner', 'manager'}:
            raise ValueError('recovery_operator_required')
        # SQLite's immediate transaction already serializes writers. PostgreSQL
        # must lock the scoped message before reading its recovery observation,
        # so a concurrent identical submission sees the committed replay receipt.
        if db.get_bind().dialect.name == 'postgresql':
            db.execute(text('SELECT id FROM outbound_message WHERE tenant_id=:tenant_id '
                            'AND id=:message_id FOR UPDATE'), params).first()
        previous = db.execute(text('SELECT payload_digest FROM outbound_recovery_observation '
            'WHERE tenant_id=:tenant_id AND message_id=:message_id'), params).scalar()
        if previous:
            if previous != digest:
                raise ValueError('recovery_observation_conflict')
            return {'status': params['status'], 'replayed': True}
        changed = db.execute(text("UPDATE outbound_message SET status=:status, provider_ref=:provider_ref, "
            "last_error='operator_observed_outcome',updated_at=:now WHERE tenant_id=:tenant_id AND id=:message_id "
            "AND status='reconciliation_required'"), params)
        if changed.rowcount != 1:
            raise ValueError('uncertain_message_required')
        db.execute(text('INSERT INTO outbound_recovery_observation '
            '(tenant_id,message_id,operator_principal,outcome,evidence_ref,provider_ref,payload_digest,observed_at) '
            'VALUES (:tenant_id,:message_id,:operator_principal,:outcome,:evidence_ref,:provider_ref,:digest,:now)'), params)
    return {'status': params['status'], 'replayed': False}
