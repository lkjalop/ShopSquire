from src.app.models.db import db_session
from sqlalchemy import text
k='payment_intent:abc123'
with db_session() as db:
    try:
        db.execute(text("CREATE TABLE IF NOT EXISTS idempotency_keys (key TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"))
        db.commit()
    except Exception as e:
        print('create table err', e)
    try:
        row = db.execute(text('SELECT 1 FROM idempotency_keys WHERE key=:k'), {'k':k}).fetchone()
        print('before select row', row)
        db.execute(text('INSERT INTO idempotency_keys (key) VALUES (:k)'), {'k':k})
        db.commit()
        row2 = db.execute(text('SELECT 1 FROM idempotency_keys WHERE key=:k'), {'k':k}).fetchone()
        print('after insert row', row2)
    except Exception as e:
        print('err', e)
