import sqlite3, json, hashlib
path = r'D:/AI/agentLumen/ShopSquire/tmp/e2e.sqlite'
conn = sqlite3.connect(path)
cur = conn.cursor()
print('PRAGMA table_info:')
cur.execute("PRAGMA table_info('decision_logs')")
print(cur.fetchall())
# Insert a row with uid_hash length 16 in input_data
uid = 'demo-user'
uid_hash = hashlib.sha256(uid.encode('utf-8')).hexdigest()[:16]
input_data = json.dumps({'uid_hash': uid_hash, 'query': 'probe for summary match', 'proposal': {'ranked_skus':['LAP-13-BASE']}})
retrieved_context = json.dumps({'agent_chain':[{'agent':'ProbeAgent','duration_ms':5}], 'products_count':1})
proposed_action = json.dumps({'sku':'LAP-13-BASE','reasoning':'probe'})
import uuid, datetime
dec_id = 'dec-probe-' + str(uuid.uuid4())
now = datetime.datetime.utcnow().isoformat()
try:
    cur.execute("INSERT INTO decision_logs (id, agent_name, valid_from, valid_to, system_from, system_to, input_data, retrieved_context, proposed_action, policy_version, approval_required, execution_status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (dec_id, 'probe-agent', now, 'infinity', now, 'infinity', input_data, retrieved_context, proposed_action, 'v1', 0, 'executed'))
    conn.commit()
    print('Inserted', dec_id)
except Exception as e:
    print('Insert failed', e)
# Show latest rows
print('\nRecent decision_logs rows:')
cur.execute("SELECT id, input_data, retrieved_context, proposed_action, valid_from FROM decision_logs ORDER BY valid_from DESC LIMIT 10")
rows = cur.fetchall()
for r in rows:
    print('ID', r[0])
    try:
        print('INPUT', json.loads(r[1]) if r[1] else None)
    except Exception:
        print('INPUT_RAW', str(r[1])[:200])
    try:
        print('RETR', json.loads(r[2]) if r[2] else None)
    except Exception:
        print('RETR_RAW', str(r[2]))
    print('---')
conn.close()
