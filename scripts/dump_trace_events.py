import sqlite3, json, sys
trace_id = sys.argv[1] if len(sys.argv) > 1 else None
if not trace_id:
    print('usage: dump_trace_events.py <trace_id>')
    raise SystemExit(1)
con = sqlite3.connect('tmp/e2e.sqlite')
con.row_factory = sqlite3.Row
cur = con.cursor()
rows = cur.execute('SELECT event_type, payload, created_at FROM decision_trace_events WHERE trace_id=? ORDER BY created_at ASC',(trace_id,)).fetchall()
for r in rows:
    payload = r['payload']
    try:
        payload = json.loads(payload)
    except Exception:
        pass
    print(r['created_at'], r['event_type'])
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print('---')
con.close()
