from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import os
os.environ['DATABASE_URL'] = 'sqlite+pysqlite:///tmp/debug_case.sqlite'
from src.app.services.cases import create_case, get_case_status
from src.app.models.db import db_session

cid = create_case(order_id='ORDER9', issue_type='damage', description='test')
print('created case id:', cid)
with db_session() as db:
    row = db.execute('SELECT id, issue_type, description FROM cases WHERE id = :id', {'id': cid}).fetchone()
    print('row:', row)
    print('get_case_status:', get_case_status(cid))
