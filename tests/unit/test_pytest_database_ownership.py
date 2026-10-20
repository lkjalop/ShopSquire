"""The imported application must use the same migrated DB as test fixtures."""

from sqlalchemy import inspect

from src.app.main import app
from src.app.models.db import get_engine


def test_module_application_uses_session_database():
    engine = get_engine()
    assert app.state.engine is engine
    assert not app.state.owns_engine
    assert "procurement_case_context_snapshot" in inspect(engine).get_table_names()


def test_module_application_rebinds_after_temporary_database(monkeypatch, tmp_path):
    from src.app.main import create_app

    original = get_engine()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "temporary.sqlite"))
    temporary = create_app()
    assert temporary.state.engine is not original


def test_module_application_still_uses_session_database():
    # The previous test's temporary app must not become the module app's DB.
    assert app.state.engine is get_engine()
    assert "procurement_case_context_snapshot" in inspect(app.state.engine).get_table_names()
