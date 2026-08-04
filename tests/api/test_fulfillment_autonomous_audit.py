"""WS-D — the autonomous-RFQ-send audit endpoint gives the operator visibility before enabling autonomy:
what auto-sent, every escalation + reason, and the LIVE enabled/killed toggle state. Filtered strictly to
the supplier_rfq_send action so unrelated adaptive-action audit rows never leak in."""
from __future__ import annotations

from fastapi.testclient import TestClient

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services import adaptive_action_gate as gate
from tests.utils import default_headers


def _seed(db):
    gate.ensure_table(db)
    gate.record_decision(db, action_type="supplier_rfq_send", decision="allow",
                         reason="autonomous_send", confidence=0.95, target="FC-A")
    gate.record_decision(db, action_type="supplier_rfq_send", decision="escalate",
                         reason="low_confidence", target="FC-B")
    gate.record_decision(db, action_type="supplier_rfq_send", decision="escalate",
                         reason="over_value_cap", target="FC-C")
    # an unrelated adaptive action must NOT appear in the autonomous-send view
    gate.record_decision(db, action_type="adjust_ranking", decision="allow", reason="noise")


def test_autonomous_audit_endpoint_summarizes_and_reports_toggle_state():
    app = create_app()
    client = TestClient(app, headers=default_headers())
    with db_session() as db:
        _seed(db)
    r = client.get("/api/v1/fulfillment/autonomous/audit?limit=100")
    assert r.status_code == 200
    data = r.json()
    assert data["summary"]["sent"] >= 1
    assert data["summary"]["escalated"] >= 2
    assert data["summary"]["by_reason"].get("low_confidence", 0) >= 1
    assert "enabled" in data and "killed" in data           # the live toggle state is surfaced
    assert data["transport"]["mode"] in ("sandbox", "smtp")  # the deploy preflight is surfaced too
    assert data["rows"] and all(row["action_type"] == "supplier_rfq_send" for row in data["rows"])  # filtered
    assert any(row["decision"] == "escalate" and row["reason"] == "over_value_cap" for row in data["rows"])
