import os

from fastapi.testclient import TestClient
from sqlalchemy import text

from src.app.main import create_app
from src.app.models.db import db_session
from src.app.schemas.ui_contracts import (
    DecisionTraceQueryResponse,
    IncidentEscalateResponse,
    IncidentMessageResponse,
    TransactionTimeseriesResponse,
)
from tests.utils import default_headers


def test_bi_timeseries_contract_shape():
    app = create_app()
    client = TestClient(app, headers=default_headers())
    resp = client.get(
        "/api/v1/admin/bi/transactions/timeseries",
        params={"granularity": "day", "start": "2026-01-01", "end": "2026-01-05"},
    )
    assert resp.status_code == 200
    TransactionTimeseriesResponse.model_validate(resp.json())


def test_decision_trace_query_contract_shape():
    app = create_app()
    client = TestClient(app, headers=default_headers())
    trace_id = "contract-trace-1"
    with db_session() as db:
        db.execute(
            text(
                "INSERT OR REPLACE INTO decision_logs "
                "(id, agent_name, valid_from, system_from, input_data, proposed_action, policy_version, approval_required, execution_status) "
                "VALUES (:id, 'contract-agent', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '{}', '{}', 'v1', 0, 'executed')"
            ),
            {"id": trace_id},
        )
        db.execute(
            text(
                "INSERT OR REPLACE INTO decision_trace_events "
                "(id, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at) "
                "VALUES ('cte-contract-1', :id, 'security_scan', 'agent', 'Security_Observer_Agent', 'system', 'policy', '{\"route\":\"review\"}', CURRENT_TIMESTAMP)"
            ),
            {"id": trace_id},
        )
        db.commit()
    resp = client.get(f"/api/v1/decisions/{trace_id}/query", params={"include_events": "true"})
    assert resp.status_code == 200
    parsed = DecisionTraceQueryResponse.model_validate(resp.json())
    assert parsed.decision_id == trace_id


def test_incident_room_public_contracts():
    os.environ["ALLOW_UNAUTH_MERCHANT_DASHBOARD"] = "1"
    app = create_app()
    client = TestClient(app, headers=default_headers())

    esc = client.post(
        "/api/v1/incidents/escalate",
        json={"case_id": "contract-case", "trace_id": "contract-trace", "reason": "contract_test"},
        headers={"host": "localhost"},
    )
    assert esc.status_code == 200
    esc_body = IncidentEscalateResponse.model_validate(esc.json())
    assert esc_body.incident_id

    msg = client.post(
        f"/api/v1/incidents/{esc_body.incident_id}/room/message",
        json={"message": "contract_test_message"},
        headers={"x-incident-token": esc_body.buyer_token},
    )
    assert msg.status_code == 200
    IncidentMessageResponse.model_validate(msg.json())

