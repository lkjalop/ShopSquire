from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.routers.decisions import _fetch_decision_audit_rows


def test_audit_read_preserves_decision_from_legacy_schema():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE decision_logs (
                id TEXT PRIMARY KEY,
                agent_name TEXT,
                valid_from TEXT,
                valid_to TEXT,
                system_from TEXT,
                system_to TEXT,
                input_data TEXT,
                retrieved_context TEXT,
                proposed_action TEXT,
                policy_version TEXT,
                approval_required INTEGER,
                execution_status TEXT,
                tenant_id TEXT
            )
            """
        ))
        conn.execute(
            text(
                """
                INSERT INTO decision_logs (
                    id, agent_name, valid_from, valid_to, system_from, system_to,
                    input_data, retrieved_context, proposed_action, policy_version,
                    approval_required, execution_status, tenant_id
                ) VALUES (
                    :id, 'Recommendation_Core', 'now', 'infinity', 'now', 'infinity',
                    '{}', '{}', '{}', 'v2', 0, 'planned', 'default'
                )
                """
            ),
            {"id": "trace-legacy"},
        )

    with Session(engine) as session:
        rows = _fetch_decision_audit_rows(session, "trace-legacy")

    assert len(rows) == 1
    assert rows[0][0] == "trace-legacy"
    assert rows[0][12] == "default"
    assert rows[0][13:] == (None, None, None)
