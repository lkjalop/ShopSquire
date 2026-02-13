from sqlalchemy import text
from src.app.config import get_settings, load_feature_flags
from src.app.models.db import get_engine
from src.app.deps import hash_uid
import json

settings = get_settings()
flags = load_feature_flags(settings.feature_flags_path)
print('feature_flags_path=', settings.feature_flags_path)
print('DECISION_LOG_WRITES_ENABLED=', flags.get('DECISION_LOG_WRITES_ENABLED'))

uid = 'demo-user'
target = hash_uid(uid)
print('uid target=', target)

eng = None
try:
    eng = get_engine()
    print('engine url=', getattr(eng, 'url', None))
except Exception as e:
    print('get_engine failed', e)

sql = "SELECT id, input_data, retrieved_context, proposed_action, valid_from FROM decision_logs ORDER BY valid_from DESC LIMIT 50"
print('Running SQL via engine...')
try:
    with eng.connect() as conn:
        res = conn.execute(text(sql)).all()
        print('rows count:', len(res))
        found = False
        for r in res:
            id_ = r[0]
            input_data = r[1]
            try:
                parsed = json.loads(input_data) if input_data else {}
            except Exception:
                parsed = {}
            uh = parsed.get('uid_hash')
            print('row id=', id_, 'uid_hash=', uh, 'matches=', uh == target)
            if uh == target:
                print('MATCH FOUND ->', id_)
                found = True
        if not found:
            print('No matching uid_hash found in top 50 rows')
except Exception as e:
    print('SQL exec failed', e)
