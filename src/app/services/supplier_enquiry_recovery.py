"""Authenticated recovery of case-bound enquiries; replacement never carries approval."""
from sqlalchemy import text
from src.app.services import supplier_enquiry_journey as journey
from src.app.services.fulfillment import person_approval as approval, outbound_queue, operator_recovery
from src.app.services.inventory_transactions import _atomic


def _authorized(db, row, principal):
    person, role = approval._person(db, row['tenant_id'], principal)
    # Active owners/managers can withdraw or replace a retired requester's
    # enquiry. Replacement stays pending and requires a new independent permit.
    if role in {'owner', 'manager'}:
        return
    requester, _ = approval._person(db, row['tenant_id'], row['requester_principal'])
    if person != requester:
        raise ValueError('recovery_operator_required')


def revoke(db, *, tenant_id, enquiry_id, operator_principal, now=None):
    row = journey.get(db, tenant_id=tenant_id, enquiry_id=enquiry_id)
    _authorized(db, row, operator_principal)
    if not row['approval_id']:
        raise ValueError('person_approval_required')
    approval.revoke(db, tenant_id=tenant_id, approval_id=row['approval_id'],
                    revoked_by=operator_principal, now=now)
    return journey.view(db, tenant_id=tenant_id, enquiry_id=enquiry_id, now=now)


def reconcile(db, *, tenant_id, enquiry_id, operator_principal, outcome, evidence_ref,
              provider_ref='', now=None):
    journey.get(db, tenant_id=tenant_id, enquiry_id=enquiry_id)
    message_id = db.execute(text('SELECT id FROM outbound_message WHERE tenant_id=:tenant AND idempotency_key=:key'),
        dict(tenant=tenant_id,key='supplier-enquiry:' + enquiry_id)).scalar()
    if not message_id:
        raise ValueError('uncertain_message_required')
    return operator_recovery.resolve(db, tenant_id=tenant_id, message_id=message_id,
        operator_principal=operator_principal, outcome=outcome, evidence_ref=evidence_ref,
        provider_ref=provider_ref, now=journey._now(now))


def renew(db, *, tenant_id, enquiry_id, operator_principal, expected_revision, reference,
          recipient_resolver, now=None):
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 100:
        raise ValueError('replacement_reference_required')
    with _atomic(db):
        if db.get_bind().dialect.name == 'postgresql':
            db.execute(text('SELECT id FROM supplier_enquiry_request WHERE tenant_id=:tenant AND id=:id FOR UPDATE'),
                       dict(tenant=tenant_id,id=enquiry_id))
        row = journey.get(db, tenant_id=tenant_id, enquiry_id=enquiry_id)
        _authorized(db, row, operator_principal)
        replacement_ref = 'renew:' + enquiry_id + ':' + reference
        existing = db.execute(text('SELECT source_reference FROM supplier_enquiry_request WHERE tenant_id=:tenant '
            'AND source_reference LIKE :prefix'),dict(tenant=tenant_id,prefix='renew:' + enquiry_id + ':%')).scalars().all()
        if any(value != replacement_ref for value in existing):
            raise ValueError('replacement_already_exists')
        clock = journey._now(now)
        message = outbound_queue.get_by_key(db, tenant_id=tenant_id,
                                           idempotency_key='supplier-enquiry:' + enquiry_id)
        status = message['status'] if message else 'not_dispatched'
        if status == 'reconciliation_required':
            raise ValueError('reconciliation_required')
        if status not in {'not_dispatched', 'blocked_authority', 'resolved_not_delivered'}:
            raise ValueError('replacement_not_safe')
        grant = db.execute(text('SELECT revoked_at,expires_at FROM person_effect_approval '
            'WHERE tenant_id=:tenant AND id=:id'), dict(tenant=tenant_id, id=row['approval_id'])).mappings().first()
        if not grant:
            raise ValueError('person_approval_required')
        if not grant['revoked_at'] and approval._time(grant['expires_at']) > clock:
            if status != 'resolved_not_delivered':
                raise ValueError('revoke_current_approval_first')
            approval.revoke(db, tenant_id=tenant_id, approval_id=row['approval_id'],
                            revoked_by=operator_principal, now=clock)
        return journey.create(db, tenant_id=tenant_id, case_id=row['case_id'],
            expected_revision=expected_revision, requester_principal=operator_principal,
            supplier_ref=row['supplier_ref'], source_reference=replacement_ref,
            recipient_resolver=recipient_resolver, now=clock)
