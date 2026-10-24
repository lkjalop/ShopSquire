"""Fixture setup for a live scheduler test; never exposes a test-clock HTTP endpoint."""
import json
import argparse
import os
from pathlib import Path
import sys
import uuid
from datetime import timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uid', help='An already enrolled buyer in the disposable runtime')
    args = parser.parse_args()
    if os.getenv('APP_ENV')!='local' or '/.artifacts/' not in os.getenv('DATABASE_URL','').replace('\\','/'):
        raise ValueError('isolated_local_database_required')
    from sqlalchemy import text
    from src.app.models.db import db_session
    from src.app.services import portfolio_qualification as journey
    from src.app.services.case_inventory_acceptance import accept_request
    uid=args.uid or 'expiry-browser-'+uuid.uuid4().hex
    with db_session() as db:
        case=journey.create_case(db,uid=uid)
        sku=db.get(journey.ProductConfiguration,journey.CONFIGURATION_ID).sku
        available=db.execute(text('SELECT SUM(available) FROM inventory_level WHERE tenant_id=:tenant AND sku=:sku'),dict(tenant=journey.TENANT,sku=sku)).scalar_one()
        result=accept_request(db,tenant_id=journey.TENANT,case_id=case['case_id'],uid=uid,
            expected_revision=1,sku=sku,quantity=1,idempotency_key=uuid.uuid4().hex,hold_duration=timedelta(seconds=25))
        if result['held_quantity']!=1:raise ValueError('probe_stock_required')
        db.commit()
    print(json.dumps(dict(uid=uid,case_id=case['case_id'],initial_available=available,accepted=result)))


if __name__=='__main__':main()
