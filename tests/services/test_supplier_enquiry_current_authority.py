"""Current case, selection and enrolled people must agree with the reviewed draft."""
import pytest
from sqlalchemy import text
from tests.services.test_supplier_enquiry_journey import db, approved, NOW, FakeTransport
from src.app.services import supplier_enquiry_journey as journey


@pytest.mark.parametrize('change', ['membership', 'person_mapping', 'revision', 'shortfall'])
def test_view_never_labels_invalid_authority_current(db, change):
    row = approved(db)
    if change == 'membership':
        db.execute(text("UPDATE operator_tenant_membership SET status='revoked' WHERE principal_hash='bob-key'"))
    elif change == 'person_mapping':
        db.execute(text("UPDATE operator_person_binding SET person_id='alice' WHERE principal_hash='bob-key'"))
    elif change == 'revision':
        db.execute(text('UPDATE shopping_cases SET revision=3'))
    else:
        db.execute(text("UPDATE inventory_reservation SET status='expired'"))
    view = journey.view(db, tenant_id='shop', enquiry_id=row['id'], now=NOW)
    assert view['approval_state'] == 'invalid'
    assert view['delivery_status'] == 'not_dispatched'


@pytest.mark.parametrize('change', ['sku', 'quantity'])
def test_selection_changes_cannot_reuse_an_equal_numeric_shortfall(db, change):
    row = approved(db)
    if change == 'sku':
        db.execute(text("UPDATE shopping_case_fulfillment_selections SET preferred_sku='OTHER'"))
    else:
        db.execute(text('UPDATE shopping_case_fulfillment_selections SET requested_quantity=15'))
        db.execute(text("UPDATE inventory_reservation SET status='expired'"))
    transport = FakeTransport()
    with pytest.raises(ValueError, match='selection_stale'):
        journey.dispatch(db, tenant_id='shop', enquiry_id=row['id'], transport=transport, now=NOW)
    assert transport.calls == 0
