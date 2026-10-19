import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from src.app.models import db as database


@pytest.mark.parametrize('through_session',[False,True])
def test_duplicate_plain_insert_cannot_replace_existing_identity(tmp_path,monkeypatch,through_session):
    engine=database._create_engine_with_fallback('sqlite:///'+str(tmp_path/'identity.sqlite3'))
    monkeypatch.setattr(database,'get_engine',lambda:engine)
    monkeypatch.setattr(database,'_ensure_minimal_sqlite_tables',lambda *_:None)
    token=database.CURRENT_REQUEST.set(None)
    try:
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE identity_probe (id TEXT PRIMARY KEY, value TEXT)'))
            conn.execute(text("INSERT INTO identity_probe VALUES ('stable','original')"))
        with pytest.raises(IntegrityError):
            if through_session:
                with database.db_session() as session:
                    session.execute("INSERT INTO identity_probe VALUES ('stable','replacement')")
                    session.commit()
            else:
                with engine.begin() as conn:
                    conn.execute(text("INSERT INTO identity_probe VALUES ('stable','replacement')"))
        with engine.connect() as conn:
            assert conn.execute(text('SELECT value FROM identity_probe')).scalar_one()=='original'
    finally:
        database.CURRENT_REQUEST.reset(token)
        engine.dispose()


def test_request_session_does_not_run_schema_writes_under_another_owners_transaction(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlalchemy import create_engine
    engine = create_engine('sqlite:///' + str(tmp_path / 'contention.sqlite3'), connect_args={'timeout': 0.01})
    database._ensure_minimal_sqlite_tables(engine)
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE contention_probe (id INTEGER PRIMARY KEY)'))
    monkeypatch.setattr(database, 'get_engine', lambda: engine)
    token = database.CURRENT_REQUEST.set(None)
    schema_writes = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'DROP ')):
            schema_writes.append(statement)

    event.listen(engine, 'before_cursor_execute', observe)
    try:
        with engine.begin() as writer:
            writer.execute(text('INSERT INTO contention_probe VALUES (1)'))
            with database.db_session() as reader:
                assert reader.execute('SELECT count(*) FROM contention_probe').scalar_one() == 0
        assert schema_writes == [], 'Opening a request session must not compete for the schema write lock'
    finally:
        event.remove(engine, 'before_cursor_execute', observe)
        database.CURRENT_REQUEST.reset(token)
        engine.dispose()


def test_failed_first_bootstrap_is_retried_after_writer_releases_the_database(tmp_path):
    from sqlalchemy import create_engine, inspect
    engine = create_engine('sqlite:///' + str(tmp_path / 'retry.sqlite3'), connect_args={'timeout': 0.01})
    try:
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE contention_probe (id INTEGER PRIMARY KEY)'))
        with engine.begin() as writer:
            writer.execute(text('INSERT INTO contention_probe VALUES (1)'))
            database._ensure_minimal_sqlite_tables(engine)
            assert 'orders' not in inspect(engine).get_table_names()
        database._ensure_minimal_sqlite_tables(engine)
        assert 'orders' in inspect(engine).get_table_names()
        assert {'email_hash', 'email_encrypted', 'phone_encrypted'}.issubset(
            {column['name'] for column in inspect(engine).get_columns('customers')})
    finally:
        engine.dispose()


def test_disposed_memory_pool_is_initialized_again_without_retaining_the_engine():
    import gc
    import weakref
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.pool import StaticPool
    engine = create_engine('sqlite://', poolclass=StaticPool)
    database._ensure_minimal_sqlite_tables(engine)
    assert 'orders' in inspect(engine).get_table_names()
    engine.dispose()
    database._ensure_minimal_sqlite_tables(engine)
    assert 'orders' in inspect(engine).get_table_names()
    reference = weakref.ref(engine)
    engine.dispose()
    del engine
    gc.collect()
    assert reference() is None
