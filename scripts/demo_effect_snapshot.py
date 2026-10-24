"""Read only aggregate effect counts from an isolated SQLite browser fixture."""
import hashlib,json,os,sqlite3
from pathlib import Path
from sqlalchemy.engine import make_url

EFFECT_TABLES=('outbound_message','refund_executions','inventory_reservation','inventory_effect_event',
    'inventory_level','inventory_stock_movement','inventory','orders','purchase_orders','draft_orders','erp_outbound_queue')


def snapshot(db):
    """Detect updates as well as inserts, across all tenants in the disposable DB."""
    state={}
    for table in EFFECT_TABLES:
        columns=[row[1] for row in db.execute('PRAGMA table_info('+table+')')]
        if not columns:
            state[table]={'status':'table_missing'}
            continue
        rows=sorted(json.dumps(dict(zip(columns,row)),sort_keys=True,default=str)
            for row in db.execute('SELECT * FROM '+table))
        state[table]={'count':len(rows),'sha256':hashlib.sha256(json.dumps(rows).encode()).hexdigest()}
    return state


def main():
    url=make_url(os.environ.get('DATABASE_URL',''));root=Path(__file__).resolve().parents[1]
    database=Path(url.database or '').resolve()
    if url.drivername!='sqlite' or not database.is_relative_to(root/'.artifacts'):
        raise ValueError('isolated_artifact_database_required')
    with sqlite3.connect('file:'+database.as_posix()+'?mode=ro',uri=True) as db:
        state=snapshot(db)
    print(json.dumps(state,sort_keys=True))

if __name__=='__main__':main()
