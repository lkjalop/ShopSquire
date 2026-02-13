import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.main import create_app
from src.app.models.db import set_engine, db_session


def _client(tmp_path, monkeypatch):
    db_path = tmp_path / "admin_security_tuning.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    eng = create_engine(f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True)
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    return TestClient(create_app())


def test_threshold_recompute_from_incident_corrections(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with db_session() as db:
        for i in range(10):
            gt = "false_positive" if i < 6 else "true_positive"
            evidence = {
                "sender_trust": {"sender_trust_score": 0.55 if gt == "false_positive" else 0.22},
                "decision_id": f"dec-{i}",
                "trace_id": f"dec-{i}",
            }
            db.execute(
                text(
                    """
                    INSERT INTO email_security_incidents
                    (id, tenant_id, severity, tags_json, reasons_json, evidence_json, ground_truth, created_at)
                    VALUES (:id, :tenant, :sev, :tags, :reasons, :evidence, :gt, CURRENT_TIMESTAMP)
                    """
                ),
                {
                    "id": f"inc-{i}",
                    "tenant": "t1",
                    "sev": "error",
                    "tags": "[]",
                    "reasons": "[]",
                    "evidence": json.dumps(evidence),
                    "gt": gt,
                },
            )
        db.commit()

    r = client.post("/api/v1/admin/security/thresholds/recompute", json={"tenant_id": "t1"}, headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("updated") is True
    thr = body.get("thresholds") or {}
    assert "sender_trust_low_threshold" in thr
    assert "ioc_fusion_malicious_threshold" in thr

    r2 = client.get("/api/v1/admin/security/thresholds?tenant_id=t1", headers={"x-api-key": "local-owner-key"})
    assert r2.status_code == 200
    t = (r2.json() or {}).get("thresholds") or {}
    assert "sender_trust_low_threshold" in t


def test_security_drilldown_endpoint_returns_unified_view(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    decision_id = "dec-drill-1"
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO decision_logs
                (id, agent_name, execution_status, tenant_id, proposed_action, retrieved_context, valid_from)
                VALUES (:id, 'email_security_agent', 'review_required', 't1', :pa, :rc, CURRENT_TIMESTAMP)
                """
            ),
            {"id": decision_id, "pa": "{}", "rc": "{}"},
        )
        db.execute(
            text(
                """
                INSERT INTO decision_trace_events
                (id, trace_id, event_type, source_type, source_id, payload, created_at)
                VALUES
                ('e1', :tid, 'tool_policy_denied', 'agent', 'ToolIntentGate', :p1, CURRENT_TIMESTAMP),
                ('e2', :tid, 'sender_trust_assessed', 'agent', 'Email_Trust_Graph_Agent', :p2, CURRENT_TIMESTAMP),
                ('e3', :tid, 'ioc_enrichment_fusion', 'agent', 'IOC_Enrichment_Agent', :p3, CURRENT_TIMESTAMP),
                ('e4', :tid, 'supply_chain_scope_check', 'agent', 'Supply_Chain_Agent', :p4, CURRENT_TIMESTAMP)
                """
            ),
            {
                "tid": decision_id,
                "p1": json.dumps({"reason": "tool_intent_denylist"}),
                "p2": json.dumps({"sender_trust_score": 0.31}),
                "p3": json.dumps({"malicious_hits": 1, "contradictions": 0}),
                "p4": json.dumps({"requires_security_review": True}),
            },
        )
        db.execute(
            text(
                """
                INSERT INTO email_security_incidents
                (id, tenant_id, severity, risk_band, tags_json, reasons_json, evidence_json, created_at)
                VALUES (:id, 't1', 'error', 'high', '[]', '[]', :ev, CURRENT_TIMESTAMP)
                """
            ),
            {
                "id": "inc-drill-1",
                "ev": json.dumps(
                    {
                        "decision_id": decision_id,
                        "trace_id": decision_id,
                        "sender_trust": {"sender_trust_score": 0.31},
                        "bank_change_detected": True,
                        "oob_verified": False,
                        "oob_verification_required": True,
                        "route": "security_review",
                        "verdict_action": "security_review",
                    }
                ),
            },
        )
        db.commit()

    r = client.get(f"/api/v1/admin/security/drilldown/{decision_id}", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("decision_id") == decision_id
    assert isinstance((body.get("tool_gate") or {}).get("denied_events"), list)
    assert isinstance(body.get("sender_trust"), dict)
    assert isinstance(body.get("oob_state"), dict)
    assert isinstance(body.get("ioc_fusion"), dict)
    assert isinstance((body.get("supply_chain") or {}).get("checks"), list)


def test_abac_deny_summary_grouping(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with db_session() as db:
        db.execute(
            text(
                """
                INSERT INTO decision_trace_events
                (id, trace_id, event_type, source_type, source_id, payload, created_at)
                VALUES
                ('ab1', 'd1', 'policy_gate', 'agent', 'ABAC_Gate_Agent', :p1, CURRENT_TIMESTAMP),
                ('ab2', 'd2', 'policy_gate', 'agent', 'ABAC_Gate_Agent', :p2, CURRENT_TIMESTAMP),
                ('ab3', 'd3', 'policy_gate', 'agent', 'ABAC_Gate_Agent', :p3, CURRENT_TIMESTAMP)
                """
            ),
            {
                "p1": json.dumps({"allow": False, "tenant_id": "t1", "resource": {"sensitivity": "high"}, "abac_reason": "mfa_stale"}),
                "p2": json.dumps({"allow": False, "tenant_id": "t1", "resource": {"sensitivity": "high"}, "abac_reason": "mfa_stale"}),
                "p3": json.dumps({"allow": True, "tenant_id": "t2", "resource": {"sensitivity": "critical"}, "abac_reason": "tenant_mismatch"}),
            },
        )
        db.commit()

    r = client.get("/api/v1/admin/security/abac/denies?hours=24", headers={"x-api-key": "local-owner-key"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("total_denies") == 2
    groups = body.get("groups") or []
    assert len(groups) == 1
    g = groups[0]
    assert g.get("tenant_id") == "t1"
    assert g.get("resource_sensitivity") == "high"
    assert g.get("abac_reason") == "mfa_stale"
    assert g.get("count") == 2


def test_security_attack_timeseries_and_geo_asn_trends(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with db_session() as db:
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS security_events (
                  id TEXT PRIMARY KEY,
                  event_time TEXT DEFAULT CURRENT_TIMESTAMP,
                  path TEXT,
                  severity TEXT,
                  verdict_score INT,
                  details TEXT,
                  escalated INTEGER DEFAULT 0,
                  blocked INTEGER DEFAULT 0
                )
                """
            )
        )
        d1 = {
            "analysis": {
                "signals": {"prompt_injection": True, "agentic_tool_abuse": True, "ip_risk": True},
                "mitre_atlas": ["AML.T0043"],
                "network": {
                    "ip_hash": "iph1",
                    "geo": {"asn": 13335, "country": "US", "is_vpn": True, "is_hosting": True, "risk": 0.82},
                    "velocity_asn_anomaly": True,
                },
            }
        }
        d2 = {
            "analysis": {
                "signals": {"social_engineering": True, "authority_impersonation": True},
                "mitre_atlas": ["AML.T0048"],
                "network": {
                    "ip_hash": "iph2",
                    "geo": {"asn": 13335, "country": "US", "is_vpn": False, "is_hosting": False, "risk": 0.3},
                    "velocity_asn_anomaly": False,
                },
            }
        }
        db.execute(
            text(
                """
                INSERT INTO security_events (id, event_time, path, severity, verdict_score, details)
                VALUES
                ('s1', CURRENT_TIMESTAMP, '/api/v1/email_security/evaluate', 'high', 91, :d1),
                ('s2', CURRENT_TIMESTAMP, '/api/v1/admin/tools/run', 'warn', 66, :d2)
                """
            ),
            {"d1": json.dumps(d1), "d2": json.dumps(d2)},
        )
        db.commit()

    ts = client.get("/api/v1/admin/security/attacks/timeseries?hours=24", headers={"x-api-key": "local-owner-key"})
    assert ts.status_code == 200
    tsb = ts.json()
    assert isinstance(tsb.get("buckets"), list)
    assert isinstance(tsb.get("totals_by_type"), list)
    assert any((x or {}).get("security_type") for x in (tsb.get("totals_by_type") or []))

    geo = client.get("/api/v1/admin/security/geoip-asn/trends?hours=24", headers={"x-api-key": "local-owner-key"})
    assert geo.status_code == 200
    geob = geo.json()
    trends = geob.get("trends") or []
    assert isinstance(trends, list)
    assert len(trends) >= 1
    first = trends[0]
    assert "network_confidence" in first
    assert "geo_trust_level" in first
    assert "asn" in first
