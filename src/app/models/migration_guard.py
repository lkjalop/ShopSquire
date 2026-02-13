from __future__ import annotations

import os
from typing import Optional, Tuple


def _is_sqlite_url(url: str | None) -> bool:
    return bool(url) and str(url).lower().startswith("sqlite")


def _alembic_head_and_current(db_url: str) -> Tuple[Optional[str], Optional[str]]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine

    # Expect to run from repo/app working directory where `alembic.ini` is present.
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    script = ScriptDirectory.from_config(cfg)
    head = script.get_current_head()

    engine = create_engine(db_url, future=True)
    with engine.connect() as conn:
        mc = MigrationContext.configure(conn)
        current = mc.get_current_revision()
    return head, current


def ensure_migrations(*, db_url: str | None = None) -> None:
    """Ensure DB schema is at Alembic head (Postgres/MySQL/etc).

    Behavior is controlled by env vars:
    - `DB_MIGRATION_GUARD` (default 1): if enabled, checks current vs head.
    - `AUTO_MIGRATE` (default 0 for local python, 1 for Docker entrypoint): if enabled, runs upgrade.

    SQLite is excluded (it's used for lightweight local tests).
    """
    db_url = db_url or os.getenv("DATABASE_URL")
    if not db_url or _is_sqlite_url(db_url):
        return

    guard = os.getenv("DB_MIGRATION_GUARD", "1").strip().lower() in ("1", "true", "yes", "on")
    auto = os.getenv("AUTO_MIGRATE", "0").strip().lower() in ("1", "true", "yes", "on")
    if not guard and not auto:
        return

    if auto:
        from alembic.config import Config
        from alembic import command

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")
        return

    head, current = _alembic_head_and_current(db_url)
    if head and current != head:
        raise RuntimeError(
            f"Database is not migrated to head (current={current!r} head={head!r}). "
            "Run: alembic -c alembic.ini upgrade head"
        )
