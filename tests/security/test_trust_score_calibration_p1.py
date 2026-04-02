import json

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.services.trust_routing import fuse_security_trust_score


def test_fuse_security_trust_score_uses_calibration(monkeypatch):
    monkeypatch.setattr(
        "src.app.services.confidence_calibration.calibrate_confidence",
        lambda raw, agent_type=None: 0.91,
    )
    out = fuse_security_trust_score(
        base_trust_score=0.42,
        sender_trust={"historical_seen_count": 0},
        ioc_malicious_hits=0,
        detonation={"malicious": False, "score": 0.0},
        ingest_blocked=False,
        auth_failed=False,
        load_shed_active=False,
    )
    assert float(out.raw_trust_score) == 0.42
    assert float(out.calibrated_trust_score) == 0.91
    assert float(out.trust_score) == 0.91
    assert str(out.calibration_source) == "confidence_calibration"


def test_admin_trust_score_calibration_report():
    app = create_app()

    # Use the TestClient as a context manager so the app lifespan runs fully
    # (and any set_engine() call inside startup completes) before we INSERT.
    # We then read get_engine() AFTER startup to guarantee we're sharing the
    # exact same engine that the API route will use.
    with TestClient(app, raise_server_exceptions=True) as client:
        # db_session() inside a request prefers req.app.state.engine over the
        # module-level get_engine(). Use app.state.engine so INSERT and the
        # API GET query share the exact same engine instance.
        from sqlalchemy.orm import Session as _SASession
        engine = app.state.engine

        with _SASession(engine) as db:
            db.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS email_security_incidents (
                      id TEXT PRIMARY KEY,
                      tenant_id TEXT,
                      severity TEXT NOT NULL,
                      tags_json TEXT NOT NULL,
                      reasons_json TEXT NOT NULL,
                      evidence_json TEXT NOT NULL,
                      created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
            )
            try:
                db.execute(text("ALTER TABLE email_security_incidents ADD COLUMN ground_truth TEXT"))
            except Exception:
                pass
            # Purge stale calibration rows from prior runs to ensure a clean baseline.
            try:
                db.execute(
                    text("DELETE FROM email_security_incidents WHERE tenant_id = 'tenant-cal'")
                )
            except Exception:
                pass
            rows = [
                ("esi-cal-1", "tenant-cal", 0.82, "true_positive"),
                ("esi-cal-2", "tenant-cal", 0.28, "false_positive"),
                ("esi-cal-3", "tenant-cal", 0.67, "false_negative"),
            ]
            for rid, tenant, score, gt in rows:
                db.execute(
                    text(
                        """
                        INSERT OR REPLACE INTO email_security_incidents
                        (id, tenant_id, severity, tags_json, reasons_json, evidence_json, ground_truth)
                        VALUES (:id, :tenant_id, 'warning', '[]', '[]', :evidence_json, :ground_truth)
                        """
                    ),
                    {
                        "id": rid,
                        "tenant_id": tenant,
                        "evidence_json": json.dumps({"trust_case": {"score": score, "calibrated_score": score}}),
                        "ground_truth": gt,
                    },
                )
            db.commit()

        r = client.get(
            "/api/v1/admin/email_security/trust-score/calibration/report?tenant_id=tenant-cal&hours=720&bins=5",
            headers={"x-api-key": "local-owner-key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert int(body.get("bins") or 0) == 5
    assert int(body.get("samples") or 0) >= 3
    assert int(body.get("labeled_samples") or 0) >= 3
    assert body.get("ece") is not None
    curve = body.get("reliability_curve") or []
    assert isinstance(curve, list)
    assert len(curve) == 5
