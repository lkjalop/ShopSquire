from src.app.models.db import engine

with engine.connect() as conn:
    try:
        res = conn.execute('SELECT COUNT(*) FROM decision_logs').fetchone()
        print('decision_logs_count', res[0] if res else 0)
    except Exception as e:
        print('error', e)
