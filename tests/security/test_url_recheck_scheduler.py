import json

from sqlalchemy import text


def test_url_recheck_scheduler_escalates_incident(monkeypatch):
    from src.app.models.db import db_session
    from src.app.services import url_recheck_scheduler as urs

    incident_id = "esi-url-recheck-1"
    decision_id = "dec-url-recheck-1"
    tenant_id = "tenant-url-recheck"

    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS email_security_incidents (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT,
                  severity TEXT,
                  risk_band TEXT,
                  reasons_json TEXT,
                  evidence_json TEXT,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_incidents
                (id, tenant_id, severity, risk_band, tags_json, reasons_json, evidence_json)
                VALUES (:id, :tenant_id, 'info', 'low', '[]', '[]', :evidence_json)
                """
            ),
            {
                "id": incident_id,
                "tenant_id": tenant_id,
                "evidence_json": json.dumps({"route": "auto_resolve", "trace_id": decision_id}),
            },
        )
        db.commit()

    monkeypatch.setattr(
        urs,
        "run_phishing_page_deep_analysis",
        lambda urls: {
            "malicious": True,
            "max_risk_score": 0.91,
            "findings": ["high_confidence_phishing_landing_page"],
            "items": [{"url_hash": "abc", "risk_score": 0.91}],
        },
    )

    sch = urs.schedule_url_rechecks(
        incident_id=incident_id,
        tenant_id=tenant_id,
        decision_id=decision_id,
        urls=["https://evil.example/login"],
        now_epoch=100,
    )
    assert sch.get("ok") is True
    assert int(sch.get("scheduled") or 0) == 2

    out = urs.run_scheduled_url_rechecks_cycle(max_jobs=10, now_epoch=100 + (3 * 60 * 60))
    assert str(out.get("status")) == "ok"
    assert int(out.get("processed") or 0) == 2
    assert int(out.get("escalated") or 0) >= 1

    with db_session() as db:
        row = db.execute(
            text("SELECT severity, risk_band, reasons_json, evidence_json FROM email_security_incidents WHERE id = :id"),
            {"id": incident_id},
        ).fetchone()
    assert row is not None
    assert str(row[0]) == "error"
    assert str(row[1]) == "high"
    reasons = json.loads(row[2] or "[]")
    evidence = json.loads(row[3] or "{}")
    assert "phishing_page_scheduled_recheck_malicious" in reasons
    scheduled = (((evidence or {}).get("phishing_page_stage") or {}).get("scheduled_rechecks") or {})
    assert "t15m" in scheduled
    assert "t2h" in scheduled
