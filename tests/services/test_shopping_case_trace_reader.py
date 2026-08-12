import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services.shopping_case_trace_reader import load_case_trace_events


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE decision_trace_events ("
            "trace_id TEXT, tenant_id TEXT, event_type TEXT, payload TEXT, created_at TEXT)"
        ))
    return Session(engine)


def test_timeout_trace_can_be_recovered_by_exact_case_identity():
    db = _db()
    payload = {
        "case_id": "sc-old-suffix",
        "research_plan_id": "crp-123",
    }
    db.execute(text(
        "INSERT INTO decision_trace_events VALUES "
        "(:trace, :tenant, :event, :payload, :created)"
    ), {
        "trace": "chat-degraded-old-suffix", "tenant": "default",
        "event": "ambiguity_exploration_projected",
        "payload": json.dumps(payload), "created": "2026-08-13T00:00:00Z",
    })
    db.commit()

    events = load_case_trace_events(
        db, case_id="sc-old-suffix", tenant_id="default",
    )

    assert len(events) == 1
    assert events[0]["trace_id"] == "chat-degraded-old-suffix"


def test_case_marker_cannot_cross_tenants():
    db = _db()
    db.execute(text(
        "INSERT INTO decision_trace_events VALUES "
        "('foreign-trace', 'foreign', 'ambiguity_exploration_projected', :payload, 'now')"
    ), {"payload": json.dumps({"case_id": "sc-case-1"})})
    db.commit()

    assert load_case_trace_events(
        db, case_id="sc-case-1", tenant_id="default",
    ) == []
