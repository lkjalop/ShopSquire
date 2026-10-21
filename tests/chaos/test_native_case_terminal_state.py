"""Native PostgreSQL checks for revision-bound evidence and retained buyer facts."""
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from src.app.models.orm import Base, ShoppingCase, ShoppingCaseContractSelection
from src.app.services import case_contract_binding as binding
from src.app.services.chat_case_continuity import restore_case_id
from src.app.services.conversation_case_state import ensure_case_state, commit_turn_transition
from src.app.services.turn_transition import TurnCommit, TurnTransition
from tests.chaos.test_request_database_owner_postgres import native_owners
from tests.migration_helpers import apply_revision
from tests.services.test_background_database_ownership import read_owner


@pytest.fixture
def native_case(native_owners):
    engine = native_owners[0]
    Base.metadata.create_all(engine, tables=[ShoppingCase.__table__, ShoppingCaseContractSelection.__table__])
    apply_revision(engine, '20260853_conversation_case_state.py')
    with Session(engine) as db:
        db.add(ShoppingCase(case_id='native-case', tenant_id='native-shop', uid='buyer', revision=1))
        db.commit()
        contract = binding.available_contracts()[0]
        binding.select_case_contract(db, tenant_id='native-shop', case_id='native-case', uid='buyer',
            expected_revision=1, contract_id=contract.id, context=contract.context)
        ensure_case_state(db, tenant_id='native-shop', case_id='native-case', session_epoch='epoch',
            subject_ref='subject-hash', authoritative_anchor={'quantity': 8, 'destination': 'Sydney',
                'budget': {'amount': 150000, 'currency': 'AUD', 'scope': 'per_unit'}})
        db.commit()
        yield db
    assert read_owner() == 2


def commit(db, key, revision, shared):
    return commit_turn_transition(db, tenant_id='native-shop', session_epoch='epoch', subject_ref='subject-hash',
        commit=TurnCommit(case_id='native-case', expected_revision=revision, source_message_id=key,
            idempotency_key=key, transition=TurnTransition.UNRESOLVED, research={'status': 'observed'},
            shared_constraints=shared))


def test_native_evidence_continuation_preserves_scope_and_material_change_invalidates(native_case):
    db = native_case
    evidence = commit(db, 'evidence', 2, {})
    assert evidence['version'] == 3
    current = binding.read_case_contract_binding(db, tenant_id='native-shop', case_id='native-case', uid='buyer')
    assert current['state'] == 'current'
    assert current['case_revision'] == 3
    assert evidence['contract_continuation']['reason'] == 'unchanged_material_inputs'
    assert restore_case_id(db, tenant_id='native-shop', uid='buyer', session_epoch='epoch', subject_ref='subject-hash') == 'native-case'
    assert restore_case_id(db, tenant_id='other-shop', uid='buyer', session_epoch='epoch', subject_ref='subject-hash') is None
    assert restore_case_id(db, tenant_id='native-shop', uid='other', session_epoch='epoch', subject_ref='subject-hash') is None
    changed = commit(db, 'quantity', 3, {'requested_quantity': 40})
    assert changed['version'] == 4
    assert changed['read_model']['right_panel']['retained_buyer_facts']['requested_quantity'] == 40
    assert binding.read_case_contract_binding(db, tenant_id='native-shop', case_id='native-case', uid='buyer')['state'] == 'stale_case_revision'


def test_native_corrected_facts_replay_and_boolean_receipt_remain_revision_bound(native_case):
    db = native_case
    shared = {'requested_quantity': 8, 'destination': 'Parramatta',
        'budget': {'amount_minor': 1000000, 'currency': 'USD', 'scope': 'total'},
        'deadline': '2030-10-12T17:00:00+11:00'}
    accepted = commit(db, 'correction', 2, shared)
    facts = accepted['read_model']['right_panel']['retained_buyer_facts']
    assert facts['requested_quantity'] == 8
    assert facts['budget'] == shared['budget']
    assert facts['destinations'] == [{'location_ref': 'Parramatta', 'quantity': 8, 'location_kind': 'unknown'}]
    assert facts['temporal']['original_expression'] == shared['deadline']
    assert accepted['read_model']['commerce_authority'] == 'none'
    assert commit(db, 'correction', 2, shared)['idempotent'] is True
    assert db.execute(text('SELECT requires_confirmation FROM conversation_case_amendment')).scalar_one() is False
    with pytest.raises(ValueError, match='case_revision_conflict'):
        commit(db, 'stale-writer', 2, {'requested_quantity': 9})
    db.rollback()
    assert db.execute(select(ShoppingCase.revision).where(ShoppingCase.case_id == 'native-case')).scalar_one() == 3
