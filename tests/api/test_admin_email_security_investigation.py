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
        "mailbox_compromise": {"risk_score": 0.81, "compromised": True, "signal_count": 3},
        "phishing_page_stage": {"stage": "queued", "detected": True, "max_risk_score": 0.78},
        "bec_kill_chain": {"stage": "Execution", "stages": ["Initial Access", "Execution"]},
    }
    # Ensure investigation actions table exists (normally done at startup)
    from src.app.routers.admin_email_security import ensure_investigation_actions_table
    ensure_investigation_actions_table()

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
    assert isinstance(body.get("explain"), dict)
    assert isinstance((body.get("explain") or {}).get("why_flagged"), list)
    assert "why_not_blocked" in (body.get("explain") or {})
    assert isinstance(body.get("timeline_summary"), dict)
    assert body.get("mailbox_compromise", {}).get("compromised") is True
    assert body.get("phishing_page_stage", {}).get("detected") is True
    assert body.get("bec_kill_chain", {}).get("stage") == "Execution"
    assert "feedback" in body

    r2 = client.post(
        f"/api/v1/admin/email_security/investigations/{incident_id}/action",
        headers={"x-api-key": "local-owner-key"},
        json={"action": "hold_payment", "note": "suspicious banking update"},
    )
    assert r2.status_code == 200
    out = r2.json()
    assert out.get("ok") is True
    assert out.get("action") == "hold_payment"

    r3 = client.post(
        f"/api/v1/admin/email_security/investigations/{incident_id}/action",
        headers={"x-api-key": "local-owner-key"},
        json={"action": "force_reauth", "note": "compromised sender suspected"},
    )
    assert r3.status_code == 200
    out3 = r3.json()
    assert out3.get("ok") is True
    assert out3.get("action") == "force_reauth"
    assert out3.get("status") == "executed"
    assert isinstance(out3.get("execution"), dict)

    # Invalid action → 400
    r4 = client.post(
        f"/api/v1/admin/email_security/investigations/{incident_id}/action",
        headers={"x-api-key": "local-owner-key"},
        json={"action": "wire_the_money", "note": "should fail"},
    )
    assert r4.status_code == 400

    # quarantine_sender → pending_implementation (not "queued")
    r5 = client.post(
        f"/api/v1/admin/email_security/investigations/{incident_id}/action",
        headers={"x-api-key": "local-owner-key"},
        json={"action": "quarantine_sender", "note": "block this domain"},
    )
    assert r5.status_code == 200
    out5 = r5.json()
    assert out5.get("status") == "pending_implementation"
    assert out5.get("warning") is not None  # explicit warning returned, not silent

    # GET on non-existent incident → 404
    r6 = client.get(
        "/api/v1/admin/email_security/investigations/does-not-exist",
        headers={"x-api-key": "local-owner-key"},
    )
    assert r6.status_code == 404

    # Actions list returned in GET after recording hold_payment
    r7 = client.get(
        f"/api/v1/admin/email_security/investigations/{incident_id}",
        headers={"x-api-key": "local-owner-key"},
    )
    assert r7.status_code == 200
    body7 = r7.json()
    action_types = [a.get("action") for a in (body7.get("actions") or [])]
    assert "hold_payment" in action_types or "force_reauth" in action_types
