"""Validate unified persistence by invoking pricing.suggest and checking event_log.

Steps:
- Enable DECISION_LOG_WRITES_ENABLED and set POLICY_VERSION
- Call /api/v1/pricing/suggest
- Query decision_logs for last id
- Call /api/v1/decisions/{id}/reopen and /extend
- Query event_log for decision.created and decision.audit entries
"""
import json
import os
from fastapi.testclient import TestClient
from sqlalchemy import text


def enable_flags():
    path = os.getenv("FEATURE_FLAGS_PATH", "config/feature_flags.json")
    flags = {
        "USE_AGENT_CAPABILITIES": True,
        "AGENT_ROLLOUT_PERCENT": 100,
        "CAPABILITIES": {"pricing": {"enabled": True, "rollout_percent": 100}},
        "KILL_SWITCH": False,
        "DECISION_LOG_WRITES_ENABLED": True,
        "POLICY_VERSION": "v-test-validate",
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flags, f, ensure_ascii=False, indent=2)


def main():
    enable_flags()
    from src.app.main import create_app
    from tests.utils import default_headers
    from src.app.models.db import db_session

    app = create_app()
    client = TestClient(app, headers=default_headers())

    # Call pricing.suggest
    r = client.get("/api/v1/pricing/suggest", params={"uid": "validate_uid", "cart_total_cents": 12000})
    print("pricing.suggest status:", r.status_code)
    # Get latest decision id
    decision_id = None
    with db_session() as db:
        row = db.execute("SELECT id FROM decision_logs ORDER BY valid_from DESC LIMIT 1").fetchone()
        decision_id = row[0] if row else None
    print("latest decision_id:", decision_id)
    if not decision_id:
        print("No decision id found; validation incomplete.")
        return

    # Trigger audits
    r2 = client.post(f"/api/v1/decisions/{decision_id}/reopen", params={"actor": "validator", "comment": "check"})
    r3 = client.post(f"/api/v1/decisions/{decision_id}/extend", params={"actor": "validator", "extend_seconds": 600})
    print("reopen status:", r2.status_code, "extend status:", r3.status_code)

    # Inspect event_log
    with db_session() as db:
        created = db.execute(
            text("SELECT id, type, payload, status, created_at FROM event_log WHERE type = 'decision.created' ORDER BY created_at DESC LIMIT 5")
        ).fetchall()
        audits = db.execute(
            text("SELECT id, type, payload, status, created_at FROM event_log WHERE type = 'decision.audit' ORDER BY created_at DESC LIMIT 5")
        ).fetchall()
        print("decision.created entries:", len(created))
        print("decision.audit entries:", len(audits))
        for r in audits:
            print("audit:", r)


if __name__ == "__main__":
    main()
