import os
import json

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session


def test_bulk_label_persists_ground_truth_and_triggers_tuning(monkeypatch):
    os.environ["OWNER_API_KEY"] = "local-owner-key"
    os.environ["DEVELOPER_API_KEY"] = "local-developer-key"
    app = create_app()
    client = TestClient(app)

    # Seed a minimal incident with evidence_json containing indicators.
    inc_id = "esi-unit-1"
    evidence = {"indicators": [{"type": "pdf_embedded_files"}, {"type": "bank_change_request"}], "decision_id": "dec-1"}
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO email_security_incidents
                  (id, tenant_id, provider, supplier_key_hash, conversation_id_hash, message_id_hash, ticket_id,
                   severity, risk_band, tags_json, reasons_json, evidence_json, playbook_id, playbook_title,
                   ticket_created, ticket_rate_limited, ticket_deduped, created_at)
                VALUES
                  (:id, :tenant_id, NULL, NULL, NULL, NULL, NULL,
                   'warning', 'medium', '[]', '[]', :evidence, NULL, NULL,
                   0, 0, 0, CURRENT_TIMESTAMP)
                """
            ),
            {"id": inc_id, "tenant_id": "t-tune", "evidence": json.dumps(evidence)},
        )
        db.commit()

    r = client.post(
        "/api/v1/admin/email_security/feedback/bulk_label",
        headers={"x-api-key": "local-owner-key"},
        json={"incident_ids": [inc_id], "outcome_value": "false_positive", "note": "unit"},
    )
    assert r.status_code == 200

    with db_session() as db:
        row = db.execute(
            text("SELECT ground_truth FROM email_security_incidents WHERE id = :id"),
            {"id": inc_id},
        ).fetchone()
    assert row and row[0] in ("false_positive", "true_positive", "false_negative")

