"""Opt-in migrated PostgreSQL checks; run with --confcutdir=tests/certification.

Never accepts an application database. This tests local durable boundaries,
not a hosted environment or an external supplier's transport.
"""
import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session


@pytest.fixture
def certified_engine(monkeypatch):
    if os.getenv('RUN_POSTGRES_CERTIFICATE') != '1':
        pytest.skip('explicit isolated PostgreSQL certificate required')
    url = make_url(os.environ['DATABASE_URL'])
    assert url.get_backend_name() == 'postgresql', 'SQLite is not PostgreSQL certification'
    assert (url.database or '').startswith('shopsquire_cert_'), 'refusing non-certificate database'
    assert url.host in {'127.0.0.1', 'localhost'}, 'hosted writes require a separate authorized certificate'
    monkeypatch.setenv('FULFILLMENT_AUTO_DRAFT_ON_COMMIT', '0')
    engine = create_engine(url)
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    with engine.connect() as db:
        assert db.scalar(text('SELECT current_database()')) == url.database
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory.from_config(Config('alembic.ini')).get_current_head()
    yield engine
    engine.dispose()


def test_explicit_sourcing_is_durable_idempotent_and_never_enqueues_dispatch(certified_engine, monkeypatch):
    from src.app.models.orm import ShoppingCase
    from src.app.routers import fulfillment_cases as route

    identity = uuid4().hex
    case_id, uid, trace = f'cert-{identity}', f'buyer-{identity}', f'trace-{identity}'
    with Session(certified_engine) as db:
        db.add(ShoppingCase(case_id=case_id, tenant_id='default', uid=uid,
                            retained_purpose='Source an unavailable product', revision=1))
        db.commit()
        before = {table: db.scalar(text(f'SELECT count(*) FROM {table}'))
                  for table in ('outbound_message', 'outbound_delivery_job')}

    @contextmanager
    def sessions():
        with Session(certified_engine) as db:
            yield db
            db.commit()

    monkeypatch.setattr(route, 'db_session', sessions)
    request = Request({'type':'http', 'method':'POST', 'path':'/', 'headers':[],
                       'query_string':b'', 'client':('127.0.0.1',12345),
                       'scheme':'http', 'server':('testserver',80)})
    body = route.OffCatalogSourcingBody(
        uid=uid, shopping_case_id=case_id, expected_case_revision=1,
        trace_id=trace, subject_label='Unstocked certificate product', quantity=25,
        commercial_terms={'currency':'AUD', 'budget_scope':'total'},
    )
    result = route.confirm_off_catalog_sourcing(body, request)
    replay = route.confirm_off_catalog_sourcing(body, request)
    assert replay['case_id'] == result['case_id'] and replay['idempotent']
    assert result['supplier_contacted'] is False
    with Session(certified_engine) as db:
        current = route.fwf.repository.current_version(db, result['case_id'], 'default')
        assert current.state == 'COMMITTED'
        assert current.state_json['sourcing_brief']['quantity'] == 25
        assert current.state_json['sourcing_brief']['supplier_contacted'] is False
        assert current.state_json['source_shopping_case'] == {'case_id':case_id, 'revision':1}
        after = {table: db.scalar(text(f'SELECT count(*) FROM {table}')) for table in before}
        assert after == before, 'draft-only acceptance must not enqueue a supplier send'
