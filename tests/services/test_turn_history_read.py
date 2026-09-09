import json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def test_turn_history_filters_tenant_and_both_time_axes():
    from src.app.services.shopping_case_trace_reader import load_case_turn_history
    engine = create_engine('sqlite:///:memory:')
    with Session(engine) as db:
        db.execute(text('CREATE TABLE conversation_case_amendment (id TEXT, tenant_id TEXT, case_id TEXT, field_name TEXT, status TEXT, proposed_value_json TEXT, observed_at TEXT, effective_at TEXT)'))
        for identifier, tenant, learned in [('first', 'a', '2026-02-01'), ('later', 'a', '2026-03-01'), ('other', 'b', '2026-02-01')]:
            db.execute(text("INSERT INTO conversation_case_amendment VALUES (:id,:tenant,'case','turn_read_model','accepted',:payload,:learned,'2026-01-01')"),
                       {'id':identifier,'tenant':tenant,'learned':learned,'payload':json.dumps({'case_revision':1,'operation_id':identifier})})
        result = load_case_turn_history(db, tenant_id='a', case_id='case', known_at='2026-02-15', valid_at='2026-01-15')
        assert [row['commit_id'] for row in result] == ['first']
        assert result[0]['read_model']['operation_id'] == 'first'
        assert load_case_turn_history(db, tenant_id='a', case_id='case', valid_at='2025-12-01') == []
    engine.dispose()
