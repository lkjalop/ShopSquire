"""Inject an uncertain fake send into an isolated browser fixture, never a public API."""
import argparse
import os
from pathlib import Path
from sqlalchemy.engine import make_url


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant',required=True)
    parser.add_argument('--enquiry',required=True)
    args=parser.parse_args()
    url=make_url(os.environ.get('DATABASE_URL',''))
    root=Path(__file__).resolve().parents[1]
    if (os.environ.get('APP_ENV')!='local' or os.environ.get('FULFILLMENT_SUPPLIER_TRANSPORT')!='sandbox'
            or url.drivername!='sqlite' or not Path(url.database or '').resolve().is_relative_to(root/'.artifacts')):
        parser.error('Requires an isolated local SQLite artifact and sandbox transport')
    from src.app.models.db import db_session
    from src.app.services.supplier_enquiry_journey import dispatch
    from src.app.services.fulfillment.transport import SendResult
    class Uncertain:
        def send(self,**_):
            return SendResult(status='unknown',provider_ref='',detail='fixture: provider response lost')
    with db_session() as db:
        result=dispatch(db,tenant_id=args.tenant,enquiry_id=args.enquiry,transport=Uncertain())
        if result['delivery_status']!='reconciliation_required':
            raise RuntimeError('Expected uncertain fixture state')
        db.commit()
    print('Simulated send requires operator reconciliation')


if __name__=='__main__':main()
