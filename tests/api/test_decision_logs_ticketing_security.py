import os
import json
from src.app.services.ticketing import TicketingAgent
from src.app.security.escalation import _create_incident
from src.app.models.db import db_session


def test_ticketing_agent_logs_decision(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/ticket.sqlite"
    ta = TicketingAgent()
    t = ta.create_ticket(title="Test Ticket", description="desc", severity="high")
    assert t.id.startswith("TKT-")
    # Verify decision_logs record
    with db_session() as db:
        row = db.execute(
            "SELECT agent_name, input_data, proposed_action FROM decision_logs WHERE agent_name='ticketing_agent' ORDER BY system_from DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        inp = json.loads(row[1])
        act = json.loads(row[2])
        assert inp.get("title") == "Test Ticket"
        assert act.get("ticket_id") == t.id
        assert act.get("status") == "open"


import pytest


@pytest.mark.parametrize("status, escalated", [("open", True), ("review", False)])
def test_security_decision_logs_paths(tmp_path, status, escalated):
    os.environ["DATABASE_URL"] = f"sqlite+pysqlite:///{tmp_path}/sec_{status}.sqlite"
    details = {"payload": {"user": "test"}, "analysis": {"heuristics": ["injection"]}}
    _create_incident(event_id=f"E_{status}", severity="high" if escalated else "warn", details=details, status=status, escalated=escalated)
    with db_session() as db:
        row = db.execute(
            "SELECT agent_name, input_data, proposed_action, retrieved_context FROM decision_logs WHERE agent_name='security_escalation_agent' ORDER BY system_from DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        inp = json.loads(row[1])
        act = json.loads(row[2])
        ctx = json.loads(row[3]) if row[3] else {}
        assert inp.get("event_id") == f"E_{status}"
        assert act.get("incident_id")
        assert act.get("escalated") is escalated
        assert isinstance(ctx, dict)
