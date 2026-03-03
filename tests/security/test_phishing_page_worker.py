import json

from sqlalchemy import text


def test_process_phishing_page_job_updates_incident_and_escalates(monkeypatch):
    from src.app.models.db import db_session
    from src.app.services import phishing_page_worker as w

    incident_id = "esi-phish-worker-1"
    decision_id = "dec-phish-worker-1"
    job_id = "pp-job-test-1"
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
                  ticket_deduped INTEGER
                )
                """
            )
        )
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_incidents
                (id, tenant_id, severity, risk_band, tags_json, reasons_json, evidence_json)
                VALUES (:id, 'tenant-w1', 'info', 'low', '[]', '[]', :evidence_json)
                """
            ),
            {
                "id": incident_id,
                "evidence_json": json.dumps(
                    {
                        "trace_id": decision_id,
                        "decision_id": decision_id,
                        "route": "auto_resolve",
                        "phishing_page_stage": {"job_id": job_id, "stage": "queued"},
                    }
                ),
            },
        )
        db.commit()

    monkeypatch.setattr(
        w,
        "run_phishing_page_deep_analysis",
        lambda urls: {
            "malicious": True,
            "max_risk_score": 0.93,
            "items": [{"url_hash": "abc", "risk_score": 0.93}],
            "findings": ["high_confidence_phishing_landing_page"],
        },
    )

    out = w.process_phishing_page_job({"job_id": job_id, "tenant_id": "tenant-w1", "urls": ["https://evil.example/login"]})
    assert out.get("ok") is True
    assert int(out.get("updated_incidents") or 0) == 1
    assert int(out.get("escalated_incidents") or 0) == 1

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
    assert "phishing_page_async_malicious" in reasons
    assert str((evidence or {}).get("route") or "") == "security_review"
    assert bool((((evidence or {}).get("phishing_page_stage") or {}).get("final") or {}).get("malicious")) is True


def test_run_phishing_page_jobs_cycle_consumes_queue(monkeypatch):
    from src.app.services import phishing_page_worker as w

    class FakeRedis:
        def __init__(self):
            self.items = [json.dumps({"job_id": "pp-job-2", "urls": ["https://example.test/login"]})]
            self.dlq = []

        def rpop(self, _queue):
            if not self.items:
                return None
            return self.items.pop()

        def lpush(self, _queue, value):
            self.dlq.append(value)
            return len(self.dlq)

    fake = FakeRedis()
    monkeypatch.setattr(w, "get_redis", lambda: fake)
    monkeypatch.setattr(w, "process_phishing_page_job", lambda job: {"ok": True, "job_id": job.get("job_id")})

    out = w.run_phishing_page_jobs_cycle(max_jobs=10)
    assert str(out.get("status")) == "ok"
    assert int(out.get("processed") or 0) == 1
    assert int(out.get("errors") or 0) == 0

