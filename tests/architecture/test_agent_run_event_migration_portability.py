from __future__ import annotations

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite


ROOT = Path(__file__).resolve().parents[2]


def _load_revision():
    path = ROOT / "alembic" / "versions" / "20260865_agent_run_event.py"
    spec = importlib.util.spec_from_file_location("agent_run_event_revision", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_boolean_default_compiles_for_postgres_and_sqlite(monkeypatch):
    revision = _load_revision()
    captured: dict[str, sa.Table] = {}

    def capture(name: str, *columns: sa.Column, **_kwargs):
        captured[name] = sa.Table(name, sa.MetaData(), *columns)

    monkeypatch.setattr(revision.op, "create_table", capture)
    monkeypatch.setattr(revision.op, "execute", lambda *_args, **_kwargs: None)
    revision.upgrade()

    table = captured["agent_run_event"]
    default = table.c.commercial_authority.server_default
    assert default is not None
    postgres_default = str(default.arg.compile(dialect=postgresql.dialect())).lower()
    sqlite_default = str(default.arg.compile(dialect=sqlite.dialect())).lower()
    assert postgres_default == "false"
    assert sqlite_default in {"0", "false"}
