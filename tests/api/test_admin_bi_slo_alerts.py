from fastapi.testclient import TestClient
from sqlalchemy import text
import json

from src.app.main import create_app
from src.app.models.db import db_session
from tests.utils import default_headers


def test_admin_bi_slo_alerts_snapshot(monkeypatch):
    from src.app.routers import admin_bi as bi

    monkeypatch.setattr(
        bi,
        "_http_p95_ms_from_prom",
        lambda path, method="GET": 3200.0 if "recommend" in str(path) else 900.0,
    )
    monkeypatch.setattr(
        bi,
        "_counter_sum_from_prom",
        lambda metric: 200.0 if str(metric) == "shopsquire_decision_events_total" else 8.0,
    )

    app = create_app()
    client = TestClient(app, headers=default_headers())

    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS nqe_feedback_events (
                  id TEXT PRIMARY KEY,
                  tenant_id TEXT,
                  trace_id TEXT,
                  question_id TEXT,
                  variant TEXT,
                  converted INTEGER,
                  latency_ms INTEGER,
                  created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        trace_rows = [
            {
                "id": "slo-tr-1",
                "trace_id": "trace-reco-1",
                "event_type": "agent_process",
                "source_type": "agent",
                "source_id": "Category_Filter_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps({"strict": True, "candidates_before": 20, "candidates_after": 0}),
            },
            {
                "id": "slo-tr-2",
                "trace_id": "trace-reco-2",
                "event_type": "candidate_retrieval",
                "source_type": "agent",
                "source_id": "Candidate_Retrieval_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps({"count": 10}),
            },
            {
                "id": "slo-tr-3",
                "trace_id": "trace-mem-1",
                "event_type": "memory_health",
                "source_type": "agent",
                "source_id": "Conversation_Memory_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps({"shortlist_lock_failed": True}),
            },
            {
                "id": "slo-tr-4",
                "trace_id": "trace-mem-2",
                "event_type": "memory_health",
                "source_type": "agent",
                "source_id": "Conversation_Memory_Agent",
                "target_type": "system",
                "target_id": None,
                "payload": json.dumps({"shortlist_lock_failed": False}),
            },
        ]
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO decision_trace_events
                (id, trace_id, event_type, source_type, source_id, target_type, target_id, payload, created_at)
                VALUES
                (:id, :trace_id, :event_type, :source_type, :source_id, :target_type, :target_id, :payload, CURRENT_TIMESTAMP)
                """
            ),
            trace_rows,
        )
        fb_rows = [
            {"id": "nqe-1", "tenant_id": "default", "trace_id": "trace-reco-1", "question_id": "ask_budget", "variant": "a", "converted": 1, "latency_ms": 120},
            {"id": "nqe-2", "tenant_id": "default", "trace_id": "trace-reco-2", "question_id": "ask_budget", "variant": "a", "converted": 0, "latency_ms": 180},
            {"id": "nqe-3", "tenant_id": "default", "trace_id": "trace-reco-3", "question_id": "ask_use_case", "variant": "b", "converted": 0, "latency_ms": 200},
            {"id": "nqe-4", "tenant_id": "default", "trace_id": "trace-reco-4", "question_id": "ask_use_case", "variant": "b", "converted": 0, "latency_ms": 220},
        ]
        db.execute(
            text(
                """
                INSERT OR REPLACE INTO nqe_feedback_events
                (id, tenant_id, trace_id, question_id, variant, converted, latency_ms, created_at)
                VALUES
                (:id, :tenant_id, :trace_id, :question_id, :variant, :converted, :latency_ms, CURRENT_TIMESTAMP)
                """
            ),
            fb_rows,
        )
        db.commit()

    resp = client.get("/api/v1/admin/bi/slo-alerts?window_hours=24")
    assert resp.status_code == 200
    body = resp.json()
    metrics = body.get("metrics") or {}
    denoms = body.get("denominators") or {}
    alerts = body.get("alerts") or []
    assert float(metrics.get("recommend_p95_latency_ms") or 0.0) == 3200.0
    assert int(denoms.get("recommend_traces") or 0) >= 2
    assert float(metrics.get("irrelevant_result_rate") or 0.0) >= 0.4
    assert float(metrics.get("shortlist_loss_rate") or 0.0) >= 0.5
    assert float(metrics.get("trace_event_drop_rate") or 0.0) > 0.03
    assert any(str(a.get("name") or "") == "recommend_p95_latency" for a in alerts)
    assert body.get("status") in {"warn", "critical"}
