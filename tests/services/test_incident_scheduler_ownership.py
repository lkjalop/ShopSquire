from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.services import incident_sla_scheduler as scheduler


@pytest.fixture
def incident_engine(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'incidents.sqlite'}",
        connect_args={"timeout": 0.05, "check_same_thread": False},
    )
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE incidents (id TEXT PRIMARY KEY, severity TEXT, "
                          "title TEXT, description TEXT, status TEXT, created_at TEXT, "
                          "sla_due_at TEXT, sla_status TEXT, sla_breach_alerted_at TEXT)"))
        conn.execute(text("CREATE TABLE effect_audit (kind TEXT)"))
        conn.execute(text("INSERT INTO incidents VALUES ('owned', 'high', 'SLA', '', "
                          "'open', :now, :due, 'active', NULL)"), {
            "now": datetime.now(timezone.utc).isoformat(),
            "due": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        })

    @contextmanager
    def sessions():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(scheduler, "db_session", sessions)
    yield engine
    engine.dispose()


@pytest.mark.parametrize("writer", ["dispatch", "trace"])
def test_external_alert_and_trace_writes_do_not_nest_in_incident_transaction(
    incident_engine, monkeypatch, writer,
):
    def write_effect(kind):
        with incident_engine.begin() as conn:
            conn.execute(text("INSERT INTO effect_audit VALUES (:kind)"), {"kind": kind})

    def dispatch(*args, **kwargs):
        if writer == "dispatch":
            write_effect("dispatch")
        return {"sent_total": 1}

    def trace(**kwargs):
        if writer == "trace":
            write_effect("trace")

    monkeypatch.setattr(scheduler, "dispatch_incident_alert", dispatch)
    monkeypatch.setattr(scheduler, "log_trace_event", trace)
    outcome = scheduler.run_cycle()
    with incident_engine.connect() as conn:
        effects = conn.execute(text("SELECT kind FROM effect_audit")).scalars().all()
        incident = conn.execute(text("SELECT sla_status, sla_breach_alerted_at FROM incidents")).one()
    assert effects == [writer], "a nested independent writer was blocked and silently lost"
    assert incident[0] == "breached"
    assert incident[1] is not None
    assert outcome["breached"] == 1


def test_start_is_idempotent_and_worker_keeps_its_application_engine(monkeypatch):
    entered = Event()
    release = Event()
    engine = object()
    app = SimpleNamespace(state=SimpleNamespace(engine=engine))
    calls = []

    def cycle(**kwargs):
        calls.append(kwargs.get("engine"))
        entered.set()
        release.wait(2)

    monkeypatch.setenv("INCIDENT_SLA_SCHEDULER_ENABLED", "1")
    monkeypatch.setattr(scheduler, "run_cycle", cycle)
    threads = []
    try:
        first = scheduler.start_incident_sla_scheduler(app)
        threads.append(first)
        assert entered.wait(1)
        second = scheduler.start_incident_sla_scheduler(app)
        threads.append(second)
        assert second is first, "starting one app twice must not orphan its first worker"
        assert calls == [engine], "background SQL must use the app engine captured at startup"
    finally:
        release.set()
        scheduler.stop_incident_sla_scheduler(app)
        for thread in threads:
            thread.join(3)


def test_stop_reports_a_worker_that_did_not_stop():
    class StuckThread:
        def is_alive(self):
            return True

        def join(self, timeout):
            pass

    thread = StuckThread()
    app = SimpleNamespace(state=SimpleNamespace(
        incident_sla_scheduler_stop=Event(), incident_sla_scheduler_thread=thread,
    ))
    with pytest.raises(RuntimeError, match="did not stop"):
        scheduler.stop_incident_sla_scheduler(app)
    assert app.state.incident_sla_scheduler_stop.is_set()
    assert app.state.incident_sla_scheduler_thread is thread


def test_explicit_engine_cycle_never_uses_the_mutable_global_factory(incident_engine, monkeypatch):
    def wrong_database():
        raise AssertionError("a worker must not resolve another app's global database")

    monkeypatch.setattr(scheduler, "db_session", wrong_database)
    monkeypatch.setattr(scheduler, "dispatch_incident_alert", lambda *a, **k: {"sent_total": 0})
    monkeypatch.setattr(scheduler, "log_trace_event", lambda **kwargs: None)
    outcome = scheduler.run_cycle(engine=incident_engine)
    assert outcome.get("ok") is True
    with incident_engine.connect() as conn:
        assert conn.execute(text("SELECT sla_status FROM incidents")).scalar_one() == "breached"


def test_application_worker_executes_owned_sql_and_stops(incident_engine, monkeypatch):
    delivered = Event()

    def dispatch(*args, **kwargs):
        delivered.set()
        return {"sent_total": 1}

    monkeypatch.setenv("INCIDENT_SLA_SCHEDULER_ENABLED", "1")
    monkeypatch.setattr(scheduler, "dispatch_incident_alert", dispatch)
    monkeypatch.setattr(scheduler, "log_trace_event", lambda **kwargs: None)
    app = SimpleNamespace(state=SimpleNamespace(engine=incident_engine))
    thread = scheduler.start_incident_sla_scheduler(app)
    try:
        assert delivered.wait(2), "the application-bound SQL path must execute, not merely start a thread"
    finally:
        scheduler.stop_incident_sla_scheduler(app)
    assert not thread.is_alive()
    with incident_engine.connect() as conn:
        assert conn.execute(text("SELECT sla_breach_alerted_at FROM incidents")).scalar_one()
