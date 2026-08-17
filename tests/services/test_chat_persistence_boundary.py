from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.app.routers import chat
from src.app.services import chat_persistence


def _engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'chat-boundary.db'}", future=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE chat_messages (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    uid TEXT NOT NULL,
                    session_id TEXT,
                    session_epoch TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    trace_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
    return engine


def test_optional_chat_evidence_uses_an_isolated_transaction(tmp_path):
    engine = _engine(tmp_path)

    class PoisonedRequestSession:
        def get_bind(self):
            return engine

        def execute(self, *_args, **_kwargs):
            raise AssertionError("request transaction must not be reused")

        def commit(self):
            raise AssertionError("request transaction must not be committed")

    message_id = chat._store_chat_message(
        PoisonedRequestSession(),
        tenant_id="tenant-a",
        uid="buyer-1",
        session_id="session-1",
        session_epoch="epoch-2",
        role="user",
        content="Need delivery next week",
        trace_id="trace-1",
    )

    with Session(engine) as session:
        row = session.execute(
            text(
                "SELECT tenant_id, uid, session_epoch, content "
                "FROM chat_messages WHERE id = :id"
            ),
            {"id": message_id},
        ).one()
    assert tuple(row) == (
        "tenant-a",
        "buyer-1",
        "epoch-2",
        "Need delivery next week",
    )


def test_chat_router_contains_no_runtime_schema_creation():
    source = Path(chat.__file__).read_text(encoding="utf-8")
    assert "CREATE TABLE" not in source.upper()


def test_completed_result_persists_message_and_structured_state(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        chat_persistence,
        "store_chat_message",
        lambda *_args, **_kwargs: calls.append("message") or "message-1",
    )
    monkeypatch.setattr(
        chat_persistence,
        "persist_chat_structured_state",
        lambda **_kwargs: calls.append("structured"),
    )

    receipt = chat_persistence.persist_chat_result(
        object(), redis=object(), uid="buyer", query="query", products=[],
        trace_id="trace", assistant_message="answer", budget={}, brands=[],
    )

    assert calls == ["message", "structured"]
    assert receipt.assistant_message == "persisted"
    assert receipt.structured_state == "persisted"
    assert receipt.errors == ()


def test_completed_result_reports_each_optional_store_failure(monkeypatch):
    def fail_message(*_args, **_kwargs):
        raise RuntimeError("message unavailable")

    def fail_structured(**_kwargs):
        raise TimeoutError("memory unavailable")

    monkeypatch.setattr(chat_persistence, "store_chat_message", fail_message)
    monkeypatch.setattr(chat_persistence, "persist_chat_structured_state", fail_structured)

    receipt = chat_persistence.persist_chat_result(
        object(), redis=object(), uid="buyer", query="query", products=[],
        trace_id="trace", assistant_message="answer", budget={}, brands=[],
    )

    assert receipt.assistant_message == "failed"
    assert receipt.structured_state == "failed"
    assert receipt.errors == (
        "assistant_message:RuntimeError",
        "structured_state:TimeoutError",
    )
