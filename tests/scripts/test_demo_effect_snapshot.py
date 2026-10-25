import sqlite3
from scripts.demo_effect_snapshot import snapshot


def test_snapshot_detects_existing_effect_updates_in_other_tenants():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE outbound_message (id TEXT,tenant_id TEXT,status TEXT)')
        db.execute("INSERT INTO outbound_message VALUES ('m','other-tenant','pending')")
        before=snapshot(db)
        assert before['orders']=={'status':'table_missing'}
        assert snapshot(db)==before
        db.execute("UPDATE outbound_message SET status='sent'")
        after=snapshot(db)
        assert before['outbound_message']['count']==after['outbound_message']['count']==1
        assert before['outbound_message']['sha256']!=after['outbound_message']['sha256']
