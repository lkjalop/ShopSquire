import json

from fastapi.testclient import TestClient
from sqlalchemy import text


def test_email_security_replay_lab_runs_and_returns_metrics():
    from src.app.main import create_app
    from src.app.models.db import db_session

    client = TestClient(create_app())
    incident_id = "esi-replay-lab-1"
    decision_id = "dec-replay-lab-1"

    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS decision_logs (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT,
                    input_data TEXT,
                    retrieved_context TEXT,
                    proposed_action TEXT,
                    policy_version TEXT,
                    execution_status TEXT,
                    valid_from TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO decision_logs
                (id, agent_name, input_data, retrieved_context, proposed_action, policy_version, execution_status, valid_from)
                VALUES
                (:id, 'email_security_agent', :input_data, :retrieved_context, :proposed_action, 'email_security_v1', 'review_required', CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": decision_id,
                "input_data": json.dumps({"subject": "wire request"}),
                "retrieved_context": json.dumps({"signals": ["prompt_injection"]}),
                "proposed_action": json.dumps({"route": "security_review", "verdict_action": "security_review"}),
            },
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS email_security_incidents (
                  id TEXT PRIMARY KEY,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                  tenant_id TEXT,
                  provider TEXT,
                  supplier_key_hash TEXT,
                  ticket_id TEXT,
                  severity TEXT,
                  risk_band TEXT,
                  playbook_id TEXT,
                  playbook_title TEXT,
                  tags_json TEXT,
                  reasons_json TEXT,
                  evidence_json TEXT,
                  ticket_created INTEGER,
                  ticket_rate_limited INTEGER,
                  ticket_deduped INTEGER,
                  decision_id TEXT,
                  trace_id TEXT
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_incidents
                (id, tenant_id, severity, evidence_json, tags_json, reasons_json)
                VALUES (:id, 'tenant-r1', 'warning', :evidence, '[]', '[]')
                """
            ),
            {
                "id": incident_id,
                "evidence": json.dumps({"decision_id": decision_id, "trace_id": decision_id}),
            },
        )
        db.commit()

    r = client.post(
        "/api/v1/admin/email_security/replay_lab/run",
        headers={"x-api-key": "local-owner-key"},
        json={"incident_ids": [incident_id]},
    )
    assert r.status_code == 200
    body = r.json()
    assert int(body.get("evaluated") or 0) >= 1
    assert "policy_verdict_counts" in body
    assert isinstance(body.get("results"), list)
    assert (body.get("results") or [])[0].get("decision_id") == decision_id
