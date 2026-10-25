from datetime import timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from src.app.models.orm import Base, Product
from src.app.services.electronics_shop_scenario import seed_scenario
from src.app.services import case_contract_binding as binding
from src.app.services.portfolio_qualification import seed_configuration, create_case, project_case, TENANT, CONTRACT_ID, NOW


@pytest.fixture
def state():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Product(sku='LAP-existing',name='Existing catalogue snapshot',price_cents=150000,specs={'ram_gb':32}))
        seed_scenario(db,tenant_id=TENANT,sku='LAP-existing',retail_cents=150000)
        db.flush()
        seed_configuration(db)
        case=create_case(db,uid='buyer')
        db.commit()
        yield db,case
    engine.dispose()


def products(result):
    return [p for s in result['projection']['shelves'] for p in s['initial']+s['next_page']]


def select(db,case):
    contract=binding.load_contract_by_id(CONTRACT_ID)
    receipt=binding.select_case_contract(db,tenant_id=TENANT,case_id=case['case_id'],uid='buyer',
        expected_revision=1,contract_id=CONTRACT_ID,context=contract.context)
    db.commit()
    return receipt


def test_selected_fixture_qualifies_in_actual_buyer_shelf(state):
    db,case=state
    select(db,case)
    result=project_case(db,case_id=case['case_id'],uid='buyer')
    assert result['simulation_only']
    assert result['commerce_authority']=='none'
    assert products(result)
    assert all(p['fit_status']=='qualified' for p in products(result))
    assert result['trace']['requirement_contract']==result['projection']['requirement_contract']


def test_unselected_revoked_and_expired_never_qualify(state):
    db,case=state
    args=dict(case_id=case['case_id'],uid='buyer')
    assert not products(project_case(db,**args))
    receipt=select(db,case)
    assert not any(p['fit_status']=='qualified' for p in products(project_case(db,**args,now=NOW+timedelta(days=2))))
    binding.revoke_case_contract(db,tenant_id=TENANT,case_id=case['case_id'],uid='buyer',
        expected_revision=2,binding_id=receipt['binding_id'])
    db.commit()
    assert not products(project_case(db,**args))


def test_other_buyer_cannot_read_fixture_case(state):
    db,case=state
    with pytest.raises(ValueError,match='owned'):
        project_case(db,case_id=case['case_id'],uid='other')


def test_qualification_reads_current_stock_instead_of_seeded_snapshot(state):
    from sqlalchemy import text
    db,case=state
    select(db,case)
    db.execute(text('UPDATE inventory_level SET reserved=on_hand,available=0'))
    db.commit()
    result=project_case(db,case_id=case['case_id'],uid='buyer')
    assert not products(result)
    db.execute(text('UPDATE inventory_level SET reserved=on_hand-1,available=1'))
    db.commit()
    result=project_case(db,case_id=case['case_id'],uid='buyer')
    assert products(result)
    assert all(sum(o['quantity'] for o in p['availability'])==3 for p in products(result))
