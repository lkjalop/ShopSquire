"""A selected scope constrains continuity without granting product authority."""
import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.app.models.orm import Base, ShoppingCase
from src.app.services.case_contract_binding import select_case_contract
from src.app.services.requirement_contract import load_requirement_contract
from src.app.services.recommendation_core.envelope import TurnEnvelope
from src.app.services.recommendation_core import turn_router
from src.app.services.taxonomy_registry import add_sold_node


@pytest.fixture
def owned_scope():
    from pathlib import Path

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(ShoppingCase(case_id='scope-case', tenant_id='scope-shop', uid='buyer', revision=1))
            add_sold_node(db, node_handle='el-6-6', tenant_id='scope-shop')
            db.commit()
            contract = load_requirement_contract(Path('config/requirement_contracts/blender-5.0-windows-opengl.json'))
            select_case_contract(db, tenant_id='scope-shop', case_id='scope-case', uid='buyer',
                                 expected_revision=1, contract_id=contract.id, context=contract.context)
            db.commit()
            yield db
    finally:
        engine.dispose()


@pytest.mark.parametrize('mode', ['model_unavailable', 'model_switch'])
@pytest.mark.parametrize('query,uid,expected', [
    ('Research Blender version 5.0 requirements against my selected scope.', 'buyer', 'continue'),
    ('Research Blender version 6.0 requirements against my selected scope.', 'buyer', 'switch'),
    ('Instead research Blender requirements.', 'buyer', 'switch'),
    ('Research an unrelated workload.', 'buyer', 'switch'),
    ('Research Blender version 5.0 requirements against my selected scope.', 'other', 'switch'),
])
def test_owned_scope_continuity_survives_router_outage_or_switch_proposal(owned_scope, mode, query, uid, expected):
    envelope = TurnEnvelope(tenant_id='scope-shop', uid=uid, query=query, trace_id='scope-test',
        session={'case_anchor': {'case_id': 'scope-case', 'revision': 2}})
    if mode == 'model_unavailable':
        decision = turn_router._bounded_fallback_decision(owned_scope, envelope, [], reason='model_unavailable')
    else:
        proposal = json.dumps({'lane': 'SEARCH', 'handle': 'el-6-6', 'confidence': 0.9,
                              'subject_action': 'switch', 'subject_role': 'COMPATIBILITY_CHECK'})
        decision = turn_router._route_turn_raw(owned_scope, envelope, llm_fn=lambda *args, **kwargs: proposal)
    assert decision.subject_action == expected
    assert decision.refusal_granted is False
    assert decision.requirements == {}
    assert not decision.case_patches
    case = owned_scope.execute(select(ShoppingCase).where(ShoppingCase.case_id == 'scope-case')).scalar_one()
    assert case.revision == 2
