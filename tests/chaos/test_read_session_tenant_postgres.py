"""Real PostgreSQL transaction tenant settings on owned primary/replica selections."""
import pytest
from sqlalchemy import text

from tests.chaos.test_request_database_owner_postgres import native_owners
from src.app.models.database_ownership import database_owner
from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.services import db_read_routing as routing


@pytest.mark.parametrize('read_class', ['strong', 'timeline'])
def test_native_read_session_reapplies_its_original_tenant_after_commit(native_owners, monkeypatch, read_class):
    monkeypatch.setenv('READ_REPLICA_URL', 'postgresql://owned-fixture/replica-selection')
    monkeypatch.setattr(routing, 'replica_lag_seconds', lambda: 0)
    monkeypatch.setattr(routing, '_get_read_engine', lambda: native_owners[1])
    initial = set_active_tenant_id('read-shop-a')
    changed = None
    try:
        with database_owner(native_owners[0]):
            with routing.read_session(read_class) as session:
                assert session.scalar(text('SELECT value FROM owner_probe')) == (0 if read_class == 'strong' else 1)
                assert session.scalar(text("SELECT current_setting('app.current_tenant', true)")) == 'read-shop-a'
                session.commit()
                changed = set_active_tenant_id('read-shop-b')
                assert session.scalar(text("SELECT current_setting('app.current_tenant', true)")) == 'read-shop-a'
                session.rollback()
            with routing.read_session(read_class) as next_session:
                assert next_session.scalar(text("SELECT current_setting('app.current_tenant', true)")) == 'read-shop-b'
    finally:
        if changed is not None:
            reset_active_tenant_id(changed)
        reset_active_tenant_id(initial)
