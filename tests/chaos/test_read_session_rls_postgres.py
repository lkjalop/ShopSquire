"""Read-session isolation with an actual restricted PostgreSQL login and reused pool."""
import secrets
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.chaos.test_request_database_owner_postgres import native_owners
from src.app.models.database_ownership import database_owner
from src.app.platform.tenant_context import reset_active_tenant_id, set_active_tenant_id
from src.app.services import db_read_routing as routing


@pytest.fixture
def restricted_read_owners(native_owners):
    admin = native_owners[0]
    role = 'read_rls_' + uuid4().hex
    password = secrets.token_hex(24)
    schemas = []
    engines = []
    role_created = False
    try:
        with admin.begin() as connection:
            connection.execute(text(f'CREATE ROLE "{role}" LOGIN PASSWORD :password '
                'NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS'), {'password': password})
        role_created = True
        for owner in native_owners[:2]:
            with owner.begin() as connection:
                schema = connection.scalar(text('SELECT current_schema()'))
                assert schema.startswith('request_owner_')
                schemas.append(schema)
                connection.execute(text('CREATE TABLE read_tenant_probe(tenant_id TEXT PRIMARY KEY, value INTEGER)'))
                connection.execute(text("INSERT INTO read_tenant_probe VALUES ('read-shop-a',7),('read-shop-b',11)"))
                connection.execute(text('ALTER TABLE read_tenant_probe ENABLE ROW LEVEL SECURITY'))
                connection.execute(text('ALTER TABLE read_tenant_probe FORCE ROW LEVEL SECURITY'))
                connection.execute(text("CREATE POLICY tenant_only ON read_tenant_probe "
                    "USING (tenant_id = current_setting('app.current_tenant',true)) "
                    "WITH CHECK (tenant_id = current_setting('app.current_tenant',true))"))
                connection.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
                connection.execute(text(f'GRANT SELECT,INSERT,UPDATE,DELETE ON read_tenant_probe TO "{role}"'))
            engines.append(create_engine(owner.url.set(username=role, password=password),
                pool_size=1, max_overflow=0, pool_timeout=5,
                connect_args={'connect_timeout': 3, 'options':
                    f'-csearch_path={schema} -cstatement_timeout=10000 -clock_timeout=5000'}))
        yield engines, schemas, role
    finally:
        for engine in engines:
            engine.dispose()
        if role_created:
            with admin.begin() as connection:
                for schema in schemas:
                    connection.execute(text(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA "{schema}" FROM "{role}"'))
                    connection.execute(text(f'REVOKE ALL PRIVILEGES ON SCHEMA "{schema}" FROM "{role}"'))
                connection.execute(text(f'DROP ROLE "{role}"'))


@pytest.mark.parametrize('index', [0, 1])
def test_unbound_restricted_connections_cannot_read_either_tenant(restricted_read_owners, index):
    engines, _, role = restricted_read_owners
    with engines[index].connect() as connection:
        assert connection.scalar(text('SELECT current_user')) == role
        assert tuple(connection.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()) == (False, False)
        assert connection.execute(text('SELECT * FROM read_tenant_probe')).all() == []


@pytest.mark.parametrize('read_class,index', [('strong', 0), ('timeline', 1)])
def test_restricted_read_sessions_enforce_tenant_across_commit_and_pool_reuse(restricted_read_owners, monkeypatch, read_class, index):
    engines, schemas, role = restricted_read_owners
    monkeypatch.setenv('READ_REPLICA_URL', 'postgresql://owned-fixture/replica-selection')
    monkeypatch.setattr(routing, 'replica_lag_seconds', lambda: 0)
    monkeypatch.setattr(routing, '_get_read_engine', lambda: engines[1])
    initial = set_active_tenant_id('read-shop-a')
    changed = None
    try:
        with database_owner(engines[0]):
            with routing.read_session(read_class) as session:
                assert session.scalar(text('SELECT current_user')) == role
                assert session.scalar(text('SELECT current_schema()')) == schemas[index]
                backend = session.scalar(text('SELECT pg_backend_pid()'))
                assert session.execute(text('SELECT tenant_id,value FROM read_tenant_probe')).all() == [('read-shop-a', 7)]
                assert session.execute(text("UPDATE read_tenant_probe SET value=99 WHERE tenant_id='read-shop-b'")).rowcount == 0
                assert session.execute(text("DELETE FROM read_tenant_probe WHERE tenant_id='read-shop-b'")).rowcount == 0
                with pytest.raises(DBAPIError) as denied:
                    session.execute(text("INSERT INTO read_tenant_probe VALUES ('foreign-shop',99)"))
                assert getattr(denied.value.orig, 'pgcode', None) == '42501'
                session.rollback()
                session.commit()
                changed = set_active_tenant_id('read-shop-b')
                assert session.execute(text('SELECT tenant_id,value FROM read_tenant_probe')).all() == [('read-shop-a', 7)]
                session.commit()
            # This is the same physical pool connection without the session binder.
            with engines[index].connect() as connection:
                assert connection.scalar(text('SELECT pg_backend_pid()')) == backend
                assert connection.scalar(text("SELECT current_setting('app.current_tenant',true)")) in (None, '')
                assert connection.execute(text('SELECT * FROM read_tenant_probe')).all() == []
            with routing.read_session(read_class) as session:
                assert session.execute(text('SELECT tenant_id,value FROM read_tenant_probe')).all() == [('read-shop-b', 11)]
                assert session.execute(text("UPDATE read_tenant_probe SET value=19 WHERE tenant_id='read-shop-b'")).rowcount == 1
                session.commit()
                assert session.execute(text('SELECT tenant_id,value FROM read_tenant_probe')).all() == [('read-shop-b', 19)]
    finally:
        if changed is not None:
            reset_active_tenant_id(changed)
        reset_active_tenant_id(initial)
