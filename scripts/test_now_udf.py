from src.app.models.db import get_engine
eng=get_engine()
print('engine url',eng.url)
con=eng.raw_connection()
cur=con.cursor()
try:
    cur.execute('select now()')
    print('now() returned', cur.fetchone())
except Exception as e:
    print('now() call failed', e)
finally:
    con.close()
