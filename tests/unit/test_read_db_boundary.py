import pytest
from sqlalchemy import text

from src.app.models import read_db


@pytest.fixture(autouse=True)
def _reset():
    read_db.reset_read_engine_for_tests()
    yield
    read_db.reset_read_engine_for_tests()


def test_explicit_read_url_wins_without_changing_transactional_engine(monkeypatch, tmp_path):
    primary = tmp_path / "primary.sqlite3"
    replica = tmp_path / "replica.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{primary}")
    monkeypatch.setenv("DATABASE_READ_URL", f"sqlite+pysqlite:///{replica}")

    engine = read_db.get_read_engine()

    assert str(replica) in str(engine.url)
    assert str(primary) not in str(engine.url)


def test_read_boundary_falls_back_explicitly_and_closes_sessions(monkeypatch, tmp_path):
    primary = tmp_path / "primary.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{primary}")
    monkeypatch.delenv("DATABASE_READ_URL", raising=False)

    dependency = read_db.get_read_db()
    session = next(dependency)
    assert session.execute(text("select 1")).scalar_one() == 1
    with pytest.raises(StopIteration):
        next(dependency)


def test_missing_database_configuration_fails_closed(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_READ_URL", raising=False)

    with pytest.raises(RuntimeError, match="DATABASE_READ_URL_or_DATABASE_URL_required"):
        read_db.get_read_engine()
