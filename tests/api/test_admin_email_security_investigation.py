import json
from fastapi.testclient import TestClient
from sqlalchemy import text


def test_admin_investigation_payload_and_actions():
    from src.app.main import create_app
    from src.app.models.db import db_session

    client = TestClient(create_app())
    incident_id = "esi-invest-1"
    trace_id = "dec-invest-1"
    evidence = {
        "trace_id": trace_id,
        "route": "security_review",
        "artifact_intel": {
            "signal_scores": {
                "total": 82.0,
                "band": "block",
                "contributions": [{"type": "vendor_homoglyph_impersonation", "weight": 35.0}],
            }
        },
    }
    with db_session() as db:
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
        # Keep insert compatible with schema variants where decision_id/trace_id columns may be absent.
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_incidents
                (id, severity, evidence_json, tags_json, reasons_json)
                VALUES (:id, 'error', :evidence, :tags, :reasons)
                """
            ),
            {
                "id": incident_id,
                "evidence": json.dumps(evidence),
                "tags": json.dumps(["email_security"]),
                "reasons": json.dumps(["auth_alignment_failed_under_dmarc_policy"]),
            },
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS decision_trace_events (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT,
                    event_type TEXT,
                    source_type TEXT,
                    source_id TEXT,
                    payload TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO decision_trace_events
                (id, trace_id, event_type, source_type, source_id, payload)
                VALUES ('evt-invest-1', :trace_id, 'security_scan', 'agent', 'Email_Security_Agent', :payload)
                """
            ),
            {"trace_id": trace_id, "payload": json.dumps({"status": "ok"})},
        )
        db.commit()

    r = client.get(f"/api/v1/admin/email_security/investigations/{incident_id}", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("incident", {}).get("id") == incident_id
    assert isinstance(body.get("timeline"), list)
    assert body.get("score_breakdown", {}).get("band") == "block"
    assert isinstance(body.get("recommended_actions"), list)

    r2 = client.post(
        f"/api/v1/admin/email_security/investigations/{incident_id}/action",
        headers={"x-api-key": "local-owner-key"},
        json={"action": "hold_payment", "note": "suspicious banking update"},
    )
    assert r2.status_code == 200
    out = r2.json()
    assert out.get("ok") is True
    assert out.get("action") == "hold_payment"
