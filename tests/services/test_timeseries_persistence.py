import os
import json
from src.app.security.observer import emit_security_event
from src.app.models.db import set_engine
from sqlalchemy import create_engine, text


def test_timeseries_write(tmp_path, monkeypatch):
    # Use a temporary sqlite file for test DB
    dbfile = tmp_path / "ts_test.sqlite"
    db_url = f"sqlite+pysqlite:///{dbfile.as_posix()}"
    os.environ["DATABASE_URL"] = db_url
    # Ensure sync persistence
    os.environ["SECURITY_OBSERVER_SYNC"] = "1"
    # Recreate module engine
    eng = create_engine(db_url, future=True)
    set_engine(eng)
    # Ensure minimal tables exist
    with eng.begin() as conn:
        conn.execute(text("CREATE TABLE IF NOT EXISTS security_events (id TEXT PRIMARY KEY, event_time TEXT, path TEXT, severity TEXT, verdict_score INT, details TEXT, escalated INTEGER DEFAULT 0, blocked INTEGER DEFAULT 0)"))
        conn.execute(text("CREATE TABLE IF NOT EXISTS security_observer_timeseries (time TEXT DEFAULT CURRENT_TIMESTAMP, event_id TEXT, severity TEXT, risk_adj REAL, insider_score REAL, tenant_id TEXT)"))
    # Call emit_security_event with provided analysis to force severity 'warn'
    payload = {"analysis": {"severity": "warn", "risk_adj": 35.0, "insider_score": 35.0, "payload": {}}}
    emit_security_event(path="/test/insider", payload=payload)
    # Verify a timeseries row was inserted
    with eng.begin() as conn:
        rows = list(conn.execute(text("SELECT event_id, severity, risk_adj, insider_score FROM security_observer_timeseries")).fetchall())
        assert len(rows) >= 1
        eid, sev, r_adj, ins = rows[0]
        assert sev == "warn"
        assert float(r_adj) >= 30.0
        assert float(ins) >= 30.0
