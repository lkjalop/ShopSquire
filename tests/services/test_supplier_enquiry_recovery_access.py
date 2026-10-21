"""Revoking a requester must not strand an enquiry beyond an owner's reach."""
import pytest
from sqlalchemy import text

from tests.services.test_supplier_enquiry_journey import db, approved, NOW, FakeTransport
from src.app.services import supplier_enquiry_journey as journey
from src.app.services import supplier_enquiry_recovery as recovery
from src.app.services.fulfillment import person_approval


def retire_requester(db):
    db.execute(text("UPDATE operator_tenant_membership SET status='revoked' WHERE principal_hash LIKE 'alice-key-%'"))


def test_current_owner_can_withdraw_approval_after_requester_is_retired(db):
    row = approved(db)
    retire_requester(db)
    result = recovery.revoke(db, tenant_id='shop', enquiry_id=row['id'],
        operator_principal='bob-key', now=NOW)
    assert result['approval_state'] == 'revoked'
    transport = FakeTransport()
    with pytest.raises(ValueError):
        journey.dispatch(db, tenant_id='shop', enquiry_id=row['id'], transport=transport, now=NOW)
    assert transport.calls == 0


def test_owner_replacement_after_retirement_requires_fresh_independent_approval(db):
    row = approved(db)
    retire_requester(db)
    person_approval.revoke(db, tenant_id='shop', approval_id=row['approval_id'], revoked_by='bob-key', now=NOW)
    replacement = recovery.renew(db, tenant_id='shop', enquiry_id=row['id'],
        operator_principal='bob-key', expected_revision=2, reference='requester-retired',
        recipient_resolver=lambda _: 'quotes@fixture.invalid', now=NOW)
    assert replacement['requester_principal'] == 'bob-key'
    assert replacement['status'] == 'pending'
    assert replacement['approval_id'] is None
    with pytest.raises(ValueError, match='distinct_people'):
        journey.approve(db, tenant_id='shop', enquiry_id=replacement['id'], approver_principal='bob-key', now=NOW)
    transport = FakeTransport()
    with pytest.raises(ValueError, match='approved_enquiry'):
        journey.dispatch(db, tenant_id='shop', enquiry_id=replacement['id'], transport=transport, now=NOW)
    assert transport.calls == 0


def test_unrelated_low_tier_operator_cannot_recover_a_retired_requester_enquiry(db):
    row = approved(db)
    retire_requester(db)
    db.execute(text("UPDATE operator_tenant_membership SET role='merchant' WHERE principal_hash='bob-key'"))
    with pytest.raises(ValueError):
        recovery.revoke(db, tenant_id='shop', enquiry_id=row['id'], operator_principal='bob-key', now=NOW)
    assert db.scalar(text('SELECT revoked_at FROM person_effect_approval WHERE id=:id'), {'id': row['approval_id']}) is None
