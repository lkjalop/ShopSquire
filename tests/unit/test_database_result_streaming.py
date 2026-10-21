"""Real db_session results must support bounded iteration used by privacy reads."""
import json

import pytest
from sqlalchemy import create_engine, text

from src.app.deps import hash_uid
from src.app.models.database_ownership import database_owner
from src.app.models.db import db_session
from src.app.routers.privacy import _subject_decisions


@pytest.fixture
def streaming_database(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'streaming.sqlite3'))
    with engine.begin() as db:
        db.execute(text('CREATE TABLE streaming_probe(id INTEGER, escalated INTEGER, blocked INTEGER)'))
        db.execute(text('INSERT INTO streaming_probe VALUES (1,0,1),(2,1,0),(3,NULL,1)'))
        db.execute(text('CREATE TABLE decision_logs(id TEXT,tenant_id TEXT,input_data TEXT,valid_from TEXT)'))
        for key, tenant, uid in [('owned','controller-a','buyer_7'),
                                  ('other','controller-a','buyerX7'),
                                  ('foreign','controller-b','buyer_7')]:
            db.execute(text('INSERT INTO decision_logs VALUES (:id,:tenant,:payload,:clock)'),
                       {'id':key,'tenant':tenant,'payload':json.dumps({'uid':uid}),'clock':'2026-10-21'})
    try:
        with database_owner(engine):
            yield engine
    finally:
        engine.dispose()


def test_streaming_mapping_iteration_is_lazy_and_keeps_boolean_conversion(streaming_database):
    with db_session() as db:
        result = db.execute(text('SELECT * FROM streaming_probe ORDER BY id'),
                            execution_options={'stream_results': True, 'yield_per': 1})
        mappings = result.mappings()
        iterator = iter(mappings)
        first = next(iterator)
        assert first == {'id':1,'escalated':False,'blocked':True}
        assert first['escalated'] is False and first['blocked'] is True
        assert mappings.all() == [{'id':2,'escalated':True,'blocked':False},
                                  {'id':3,'escalated':None,'blocked':True}]
        result.close()
        assert result.closed


def test_streaming_row_iteration_keeps_the_existing_tuple_contract(streaming_database):
    with db_session() as db:
        result = db.execute(text('SELECT * FROM streaming_probe ORDER BY id'),
                            execution_options={'stream_results':True,'yield_per':1})
        rows = list(result)
        assert rows == [(1,False,True),(2,True,False),(3,None,True)]
        assert rows[0][1] is False and rows[0][2] is True
        result.close()
    assert streaming_database.pool.checkedout() == 0


def test_privacy_subject_stream_uses_real_compatibility_sessions(streaming_database):
    with db_session() as db:
        rows = _subject_decisions(db,tenant_id='controller-a',uid='buyer_7',uid_hash=hash_uid('buyer_7'))
    assert [r['id'] for r in rows] == ['owned']
    assert streaming_database.pool.checkedout() == 0
