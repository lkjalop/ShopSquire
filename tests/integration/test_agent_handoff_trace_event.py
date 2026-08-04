import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.app.models.db import db_session, set_engine
from src.app.models.init_db import ensure_metadata
from src.app.services.agent_handoff import AgentHandoff


class _DummyBus:
    def __init__(self):
        self.messages = []

    async def publish(self, msg):  # pragma: no cover - executed via asyncio.run
        self.messages.append(msg)


def test_agent_to_agent_handoff_emits_trace_event(monkeypatch, tmp_path):
    import asyncio

    db_path = tmp_path / "handoff.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setenv("DISABLE_TRACING", "1")
    # General CI runs with APP_ENV=testing, where downstream trace delivery is
    # intentionally off by default. This contract explicitly exercises it.
    monkeypatch.setenv("TRACE_EVENT_OUTBOX_ENABLED", "1")

    eng = create_engine(
        f"sqlite+pysqlite:///{db_path}", connect_args={"check_same_thread": False}, future=True
    )
    set_engine(eng)
    try:
        import src.app.models.db as dbmod

        dbmod.SessionLocal = sessionmaker(bind=eng, future=True)
    except Exception:
        pass
    ensure_metadata()

    async def _run():
        bus = _DummyBus()
        h = AgentHandoff(bus=bus)
        trace_id = "trace-handoff-1"
        out = await h.request_handoff(
            from_agent="Inventory_Agent",
            to_agent="Approval_Agent",
            reason="amount_threshold",
            context={"amount_cents": 250000, "currency": "USD"},
            trace_id=trace_id,
        )
        assert out.get("status") == "handoff_requested"
        assert bus.messages

        with db_session() as db:
            row = db.execute(
                text(
                    "SELECT payload FROM decision_trace_events "
                    "WHERE trace_id = :t AND event_type = 'handoff_requested' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"t": trace_id},
            ).fetchone()
            assert row is not None
            payload = json.loads(row[0] or "{}")
            assert payload.get("reason") == "amount_threshold"
            assert "context_keys" in payload
            assert payload.get("_schema_version") == "1.0"
            assert payload.get("_producer") == "Inventory_Agent"

            outbox = db.execute(
                text(
                    "SELECT id, type FROM event_log WHERE id LIKE 'trace:%' "
                    "ORDER BY created_at DESC LIMIT 1"
                )
            ).fetchone()
            assert outbox is not None
            assert outbox[1] == "decision_trace_event"

    asyncio.run(_run())
