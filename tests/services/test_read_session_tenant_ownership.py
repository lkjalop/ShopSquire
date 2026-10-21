import pytest
from sqlalchemy.orm import Session

from src.app.models.db import create_runtime_engine
from src.app.models.database_ownership import database_owner
from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.services import db_read_routing as routing


@pytest.mark.parametrize('read_class', ['strong', 'timeline'])
def test_read_session_binds_the_active_tenant_before_yielding(monkeypatch, read_class):
    monkeypatch.delenv('READ_REPLICA_URL', raising=False)
    engine = create_runtime_engine('sqlite://')
    token = set_active_tenant_id('read-session-tenant')
    try:
        with database_owner(engine), routing.read_session(read_class) as session:
            assert session.get_bind() is engine
            assert session.info.get('tenant_id') == 'read-session-tenant'
            assert session.info.get('_shopsquire_bound_tenant') == 'read-session-tenant'
    finally:
        reset_active_tenant_id(token)
        engine.dispose()


def test_read_session_closes_its_owned_session_when_tenant_binding_fails(monkeypatch):
    engine = create_runtime_engine('sqlite://')
    session = Session(engine)
    closed = []
    original_close = session.close

    def close():
        closed.append(True)
        original_close()

    def reject(_session):
        raise ValueError('controlled tenant binding failure')

    monkeypatch.setattr(session, 'close', close)
    monkeypatch.setattr(routing, 'sessionmaker', lambda **_kwargs: lambda: session)
    monkeypatch.setattr('src.app.platform.tenant_session.bind_session_tenant', reject)
    yielded = []
    try:
        with database_owner(engine), pytest.raises(ValueError, match='controlled tenant binding failure'):
            with routing.read_session('strong'):
                yielded.append(True)
        assert yielded == []
        assert closed == [True], 'failed tenant binding must not abandon the newly created session'
    finally:
        original_close()
        engine.dispose()
