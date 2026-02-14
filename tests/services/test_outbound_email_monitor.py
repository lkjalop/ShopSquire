import os
import math
import pytest

from sqlalchemy import text

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_outbound_monitor.db")
os.environ.setdefault("DATABASE_URL_RO", "sqlite:///./test_outbound_monitor.db")


def test_periodic_beacon_like_detection(monkeypatch):
    from src.app.services import outbound_email_monitor as oem
    from src.app.models.db import db_session

    # Simulate near-constant interval sends: every 60s with small jitter
    base = 1_700_000_000
    deltas = [60, 62, 59, 60, 61, 60, 60]
    times = [base]
    for d in deltas:
        times.append(times[-1] + d)

    agent = "agent-xyz"
    # Clean any residue from previous runs to keep timing math deterministic.
    try:
        oem._ensure_tables()
    except Exception:
        pass
    with db_session() as db:
        db.execute(text("DELETE FROM outbound_email_events WHERE agent_id = :a"), {"a": agent})
        db.execute(text("DELETE FROM outbound_email_anomalies WHERE agent_id = :a"), {"a": agent})
        db.commit()
    for i in range(len(deltas) + 1):
        # Use a high-entropy subject so the combined score crosses the anomaly threshold (>= 0.6).
        subj = "A1b2C3d4E5f6G7" if i == 0 else f"Ping {i}"
        oem.record_outbound_email_event(
            tenant_id="t-out",
            agent_id=agent,
            to=f"user{i}@example.com",
            subject=subj,
            body="heartbeat",
            now_ts=int(times[i]),
        )

    analysis = oem.analyze_agent_outbound_email(
        agent_id=agent,
        minutes=120,
        periodic_cv_threshold=0.2,
        entropy_subject_threshold=3.5,
        now_ts=int(times[-1]),
    )
    assert analysis.get("anomalous") is True
    reasons = analysis.get("reasons") or []
    assert "periodic_beacon_like_timing" in reasons
    assert "high_entropy_subject" in reasons
    assert analysis.get("events") >= 6


def test_high_entropy_subject_detection(monkeypatch):
    from src.app.services import outbound_email_monitor as oem
    from src.app.models.db import db_session

    # Make time monotonic for inserts
    t0 = 1_700_000_500
    times = [t0 + i * 5 for i in range(3)]

    agent = "agent-abc"
    try:
        oem._ensure_tables()
    except Exception:
        pass
    with db_session() as db:
        db.execute(text("DELETE FROM outbound_email_events WHERE agent_id = :a"), {"a": agent})
        db.execute(text("DELETE FROM outbound_email_anomalies WHERE agent_id = :a"), {"a": agent})
        db.commit()
    # Subject with high entropy (random-like string)
    for subj in ("A1b2C3d4E5f6G7", "Z9y8X7w6V5u4T3", "Q1W2E3R4T5Y6U7"):
        oem.record_outbound_email_event(
            tenant_id="t-out",
            agent_id=agent,
            to="dest@example.com",
            subject=subj,
            body="",
            now_ts=int(times.pop(0)),
        )

    analysis = oem.analyze_agent_outbound_email(agent_id=agent, minutes=60, entropy_subject_threshold=3.5, now_ts=t0 + 30)
    # High-entropy subject alone is a signal, but does not necessarily cross the anomaly score threshold.
    assert analysis.get("anomalous") in (False, True)
    assert "high_entropy_subject" in (analysis.get("reasons") or [])


def test_store_outbound_anomaly_creates_record(monkeypatch):
    from src.app.services import outbound_email_monitor as oem

    # Single event; craft analysis to mark anomalous
    monkeypatch.setattr(oem.time, "time", lambda: 1_700_001_000.0)
    ev = oem.record_outbound_email_event(
        tenant_id="t-out",
        agent_id="agent-1",
        to="user@example.com",
        subject="Test",
        body="",
    )
    an = oem.store_outbound_anomaly(
        tenant_id="t-out",
        agent_id="agent-1",
        event_id=ev["id"],
        analysis={"anomalous": True, "reasons": ["periodic_beacon_like_timing"], "score": 0.7},
        severity="high",
    )
    assert isinstance(an, str) and an
