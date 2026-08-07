from __future__ import annotations

from pathlib import Path

from src.app.models.db import create_runtime_engine


def test_application_factory_uses_canonical_bounded_engine_factory() -> None:
    source = Path("src/app/main.py").read_text(encoding="utf-8")
    assert "dbmod.create_runtime_engine(url)" in source
    assert "eng = create_engine(url, pool_pre_ping=True, future=True)" not in source


def test_postgres_runtime_engine_registers_bounded_failure_observer() -> None:
    engine = create_runtime_engine("postgresql+psycopg2://user:pass@127.0.0.1:9/db")
    try:
        assert len(list(engine.dialect.dispatch.handle_error)) == 1
    finally:
        engine.dispose()
