"""A factory's ambient engine change cannot move the availability catalogue."""
from sqlalchemy import text

from src.app.models import db as database
from src.app.models.orm import Base
from tests.api import test_bulk_availability_e2e as availability


def test_bulk_availability_keeps_catalogue_with_its_request_owner(monkeypatch, tmp_path):
    original_engine = database.get_engine()
    foreign = database.create_runtime_engine(f"sqlite+pysqlite:///{tmp_path/'foreign-availability.sqlite3'}")
    Base.metadata.create_all(foreign)
    factory = availability.create_app
    changed = []

    def changes_global_engine():
        app = factory()
        changed.append((app, app.state.engine, getattr(app.state,'owns_engine',False)))
        database.set_engine(foreign)
        return app

    monkeypatch.setattr(availability,'create_app',changes_global_engine)
    try:
        availability.test_bulk_availability_query_wired_end_to_end(monkeypatch)
        with foreign.connect() as db:
            assert db.scalar(text("SELECT count(*) FROM products WHERE sku LIKE 'GAM-%'")) == 0
    finally:
        database.set_engine(original_engine)
        for app, prior, owned in changed:
            selected = app.state.engine
            app.state.engine = prior
            app.state.owns_engine = owned
            if selected not in (original_engine,foreign,prior):
                selected.dispose()
        foreign.dispose()
