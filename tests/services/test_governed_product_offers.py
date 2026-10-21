from datetime import datetime,timezone,timedelta
import json
import pytest
from sqlalchemy import create_engine,text
from sqlalchemy.orm import Session
from src.app.models.orm import Base,Product,ProductConfiguration,ProductEvidenceObservation,ShoppingCase
from src.app.services import governed_product_offers as offers

NOW=datetime(2026,10,1,tzinfo=timezone.utc)

@pytest.fixture
def db():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine,tables=[Product.__table__,ProductConfiguration.__table__,ProductEvidenceObservation.__table__,ShoppingCase.__table__])
    with Session(engine) as db:
        db.execute(text(offers.DDL))
        db.execute(text('CREATE TABLE draft_orders(id TEXT PRIMARY KEY,tenant_id TEXT,customer_id TEXT,status TEXT,line_items TEXT,version INTEGER,updated_at TEXT)'))
        db.execute(text("INSERT INTO draft_orders VALUES ('cart','shop','buyer','draft','[]',0,NULL)"))
        db.execute(text('CREATE TABLE inventory_level(tenant_id TEXT,sku TEXT,available INTEGER)'))
        for sku,price in [('BASE',10000),('ADD',2000),('UPGRADE',15000)]:
            db.add(Product(id=sku,sku=sku,name=sku,price_cents=price,currency='AUD'))
            db.add(ProductConfiguration(id=sku,tenant_id='shop',sku=sku,title=sku,configuration_hash=sku,price_cents=price,currency='AUD',price_observed_at=NOW))
            db.execute(text("INSERT INTO inventory_level VALUES ('shop',:sku,10)"),{'sku':sku})
        db.add(ShoppingCase(case_id='case',tenant_id='shop',uid='buyer',revision=1))
        db.flush()
        for target,kind,benefit in [('ADD','cross_sell','Provides supported portable backup.'),('UPGRADE','upgrade','Provides greater memory capacity for the stated need.')]:
            db.add(ProductEvidenceObservation(id='evidence-'+target,configuration_id='BASE',attribute_key='supported_product_relation',
                value_json={'target_configuration_id':target,'kind':kind,'need':'capacity','supported':True,'benefit':benefit},
                claim_class='attested',evidence_status='observed',source_id='reviewed-fixture',source_record_id=target,
                source_excerpt=benefit,observed_at=NOW,expires_at=NOW+timedelta(days=1)))
        db.commit();yield db
    engine.dispose()


def propose(db,target='ADD'):
    return offers.propose(db,tenant_id='shop',case_id='case',uid='buyer',expected_revision=1,
        cart_id='cart',base_configuration_id='BASE',target_configuration_id=target,need='capacity',quantity=2,now=NOW)


@pytest.mark.parametrize('target,total,increment',[('ADD',24000,4000),('UPGRADE',30000,10000)])
def test_supported_offer_requires_explicit_acceptance_and_is_replay_safe(db,target,total,increment):
    proposal=propose(db,target)
    assert proposal['total_cents']==total and proposal['incremental_cents']==increment
    assert json.loads(db.execute(text('SELECT line_items FROM draft_orders')).scalar())==[]
    result=offers.accept(db,tenant_id='shop',case_id='case',uid='buyer',offer_id=proposal['id'],now=NOW)
    assert result['status']=='accepted' and result['case_revision']==2
    again=offers.accept(db,tenant_id='shop',case_id='case',uid='buyer',offer_id=proposal['id'],now=NOW)
    assert again==result
    assert db.execute(text('SELECT version FROM draft_orders')).scalar()==1


@pytest.mark.parametrize('change',['unknown','incompatible','conflict','revoked','expired','wrong_need'])
def test_relationship_candidate_cannot_manufacture_compatibility(db,change):
    fact=db.get(ProductEvidenceObservation,'evidence-ADD')
    if change=='unknown':db.delete(fact)
    if change in ('incompatible','wrong_need'):
        fact.value_json={**fact.value_json,**({'supported':False} if change=='incompatible' else {'need':'other'})}
    if change=='conflict':fact.conflict_group='disagreement'
    if change=='revoked':fact.evidence_status='revoked'
    if change=='expired':fact.expires_at=NOW-timedelta(seconds=1)
    db.flush()
    with pytest.raises(ValueError):propose(db)
    assert db.execute(text('SELECT version FROM draft_orders')).scalar()==0


@pytest.mark.parametrize('change',['revision','price','stock','revoked','expiry','cart','tenant','uid'])
def test_consumption_revalidates_offer_before_any_cart_effect(db,change):
    proposal=propose(db)
    if change=='revision':db.execute(text('UPDATE shopping_cases SET revision=2'))
    if change=='price':db.get(ProductConfiguration,'ADD').price_cents=9999
    if change=='stock':db.execute(text("UPDATE inventory_level SET available=0 WHERE sku='ADD'"))
    if change=='revoked':db.get(ProductEvidenceObservation,'evidence-ADD').evidence_status='revoked'
    if change=='cart':db.execute(text('UPDATE draft_orders SET version=1'))
    db.flush()
    with pytest.raises(ValueError):offers.accept(db,tenant_id='other' if change=='tenant' else 'shop',
        case_id='case',uid='other' if change=='uid' else 'buyer',offer_id=proposal['id'],
        now=NOW+timedelta(hours=1) if change=='expiry' else NOW)
    assert json.loads(db.execute(text('SELECT line_items FROM draft_orders')).scalar())==[]


def test_declined_and_superseded_offers_cannot_change_the_cart(db):
    first=propose(db)
    offers.decline(db,tenant_id='shop',case_id='case',uid='buyer',offer_id=first['id'])
    with pytest.raises(ValueError):offers.accept(db,tenant_id='shop',case_id='case',uid='buyer',offer_id=first['id'],now=NOW)
    second=propose(db);propose(db,target='UPGRADE')
    with pytest.raises(ValueError):offers.accept(db,tenant_id='shop',case_id='case',uid='buyer',offer_id=second['id'],now=NOW)
    assert db.execute(text('SELECT version FROM draft_orders')).scalar()==0


def test_offer_uses_existing_cart_discount_math_and_generic_relationships(db):
    base=db.get(Product,'BASE');base.name='Test Laptop';base.price_cents=120000
    db.get(ProductConfiguration,'BASE').price_cents=120000
    accessory=db.get(Product,'ADD');accessory.name='Portable SSD';accessory.price_cents=50000
    db.get(ProductConfiguration,'ADD').price_cents=50000
    db.flush()
    result=offers.evaluate(db,tenant_id='shop',base_configuration_id='BASE',target_configuration_id='ADD',need='capacity',quantity=1,now=NOW)
    assert result['applied_discount_cents']==18000 and result['total_cents']==152000
    # Same authority/acceptance rules work for a non-electronics pair; category
    # popularity does not replace the explicit relationship evidence.
    base.name='Office chair';accessory.name='Chair floor mat';db.flush()
    result=offers.evaluate(db,tenant_id='shop',base_configuration_id='BASE',target_configuration_id='ADD',need='capacity',quantity=1,now=NOW)
    assert result['total_cents']==170000
