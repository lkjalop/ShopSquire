import os
import sqlite3
import json

# Determine sqlite path from DATABASE_URL or fallback to tmp/e2e.sqlite
db_url = os.environ.get('DATABASE_URL') or os.environ.get('DATABASE') or ''
if db_url.startswith('sqlite'):
    # handle sqlite+pysqlite:///path or sqlite:///path
    path = db_url.split(':///')[-1]
else:
    path = 'tmp/e2e.sqlite'

print('Using sqlite path:', path)
if not os.path.exists(path):
    print('DB file not found:', path)
    raise SystemExit(1)

conn = sqlite3.connect(path)
cur = conn.cursor()

# List tables
try:
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print('Tables found:', tables)
except Exception as e:
    print('Error listing tables:', e)

# Try to query decision_trace_events
if 'decision_trace_events' in tables:
    try:
        rows = cur.execute('SELECT id, event_type, created_at FROM decision_trace_events ORDER BY created_at DESC LIMIT 5').fetchall()
        print('Latest decision_trace_events (up to 5):')
        for r in rows:
            print(' -', r)
    except Exception as e:
        print('Failed to read decision_trace_events:', e)
else:
    print('Table decision_trace_events not present')

# Try to query decision_traces table for last trace
if 'decision_traces' in tables:
    try:
        row = cur.execute('SELECT id, uid, created_at FROM decision_traces ORDER BY created_at DESC LIMIT 1').fetchone()
        print('Latest decision_traces row:', row)
    except Exception as e:
        print('Failed to read decision_traces:', e)
else:
    print('Table decision_traces not present')

conn.close()
