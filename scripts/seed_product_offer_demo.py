"""Bind explicit fictional pair evidence to existing catalogue identities."""
import json,os,sys,hashlib
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    if os.getenv('APP_ENV') not in ('local','test') or '/.artifacts/' not in os.getenv('DATABASE_URL','').replace('\\','/'):
        raise ValueError('isolated_local_database_required')
    from sqlalchemy import text
    from src.app.models.db import db_session
    from src.app.models.orm import ProductConfiguration,ProductEvidenceObservation
    from src.app.services.commerce_catalog import upsert_inventory
    config=json.loads(Path('config/product_offer_demo.json').read_text())
    tenant=config['tenant_id'];now=datetime.now(timezone.utc)
    with db_session() as db:
        for entry in [config['base'],*config['candidates']]:
            row=db.execute(text('SELECT id,price_cents,currency FROM products WHERE sku=:sku'),{'sku':entry['sku']}).first()
            if not row:raise ValueError('existing_catalogue_identity_required')
            identity=tenant+':'+entry['sku']
            configuration=db.get(ProductConfiguration,identity)
            if not configuration:
                configuration=ProductConfiguration(id=identity,tenant_id=tenant,product_id=row[0],sku=entry['sku'],
                    title=entry['label'],configuration_hash=hashlib.sha256((config['version']+entry['sku']).encode()).hexdigest(),
                    source_url='https://fixture.invalid/product-offers',price_cents=row[1],currency=row[2])
                db.add(configuration)
            configuration.price_cents=row[1];configuration.currency=row[2];configuration.price_observed_at=now
            db.flush()
            if not db.execute(text('SELECT 1 FROM inventory_level WHERE tenant_id=:tenant AND sku=:sku'),dict(tenant=tenant,sku=entry['sku'])).first():
                upsert_inventory(db,tenant_id=tenant,sku=entry['sku'],location_id='simulation',on_hand=10,reserved=0)
        base=tenant+':'+config['base']['sku']
        for entry in config['candidates']:
            if entry['supported'] is None:continue
            identity=config['version']+':'+entry['sku']
            fact=db.get(ProductEvidenceObservation,identity)
            if not fact:
                fact=ProductEvidenceObservation(id=identity,configuration_id=base,attribute_key='supported_product_relation',
                    claim_class='attested',evidence_status='observed',source_id='simulation:reviewed-pair-fixture',source_record_id=identity)
                db.add(fact)
            fact.value_json=dict(target_configuration_id=tenant+':'+entry['sku'],kind=entry['kind'],need=entry['need'],
                supported=entry['supported'],benefit=entry['benefit'],simulation_only=True)
            fact.source_excerpt='FICTIONAL PAIR EVIDENCE. '+entry['benefit']+' This does not certify the real named products.'
            fact.observed_at=now;fact.expires_at=now+timedelta(days=1)
        db.commit()
    print(json.dumps({'tenant':tenant,'existing_catalogue_products':5,'fictional_relationships':3,'observed_at':now.isoformat()}))

if __name__=='__main__':main()
