from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.app.platform.tenant_session import bind_session_tenant


def test_postgres_transaction_hook_reapplies_the_original_tenant_after_commit():
    with Session() as session:
        bind_session_tenant(session, tenant_id="shop-a")
        calls = []
        connection = SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql"),
            execute=lambda statement, values: calls.append((str(statement), values)),
        )
        # Each transaction, including one after commit/rollback, invokes this hook.
        session.dispatch.after_begin(session, object(), connection)
        session.dispatch.after_begin(session, object(), connection)
        assert calls == [("SELECT set_config('app.current_tenant', :tenant, true)",
                          {"tenant": "shop-a"})] * 2


@pytest.mark.parametrize("tenant", [None, "", "   ", 12])
def test_invalid_explicit_tenant_cannot_bind_a_session(tenant, monkeypatch):
    monkeypatch.setattr("src.app.platform.tenant_session.current_tenant_id", lambda: "")
    with Session() as session, pytest.raises(ValueError, match="database_tenant_required"):
        bind_session_tenant(session, tenant_id=tenant)


def test_repeated_binding_is_idempotent_and_cannot_change_session_tenant():
    with Session() as session:
        assert bind_session_tenant(session, tenant_id="shop-a") is session
        assert bind_session_tenant(session, tenant_id="shop-a") is session
        assert len(list(session.dispatch.after_begin)) == 1
        with pytest.raises(ValueError, match="rebinding"):
            bind_session_tenant(session, tenant_id="shop-b")
        assert session.info["tenant_id"] == "shop-a"


def test_binding_after_a_transaction_started_is_rejected():
    with Session() as session:
        session.begin()
        with pytest.raises(ValueError, match="before_transaction"):
            bind_session_tenant(session, tenant_id="shop-a")


def test_sqlite_session_does_not_execute_postgres_settings():
    engine = create_engine("sqlite://")
    try:
        with Session(engine) as session:
            bind_session_tenant(session, tenant_id="shop-a")
            with session.begin():
                assert session.connection().dialect.name == "sqlite"
            assert session.info["tenant_id"] == "shop-a"
    finally:
        engine.dispose()
