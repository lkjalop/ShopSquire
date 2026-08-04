from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
import sys


@contextmanager
def _database_url_environment(db_url: str):
    """Make Alembic's env.py see the explicit CLI database target."""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = db_url
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


def main() -> int:
    ap = argparse.ArgumentParser(description="Upgrade DB to Alembic head and run shadow checks.")
    ap.add_argument("--db-url", help="Database URL (overrides DATABASE_URL env)")
    ap.add_argument("--no-upgrade", action="store_true", help="Skip upgrade, only run checks")
    args = ap.parse_args()

    db_url = args.db_url or os.getenv("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL required (or pass --db-url)")
        return 2

    if not args.no_upgrade:
        from alembic.config import Config
        from alembic import command

        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", db_url)
        print(f"[verify] alembic upgrade head (db_url={db_url})")
        # alembic/env.py intentionally prefers DATABASE_URL so normal CLI
        # deployments can use application settings. Mirror the explicit
        # --db-url into that environment for this programmatic invocation;
        # setting only sqlalchemy.url is otherwise overwritten by .env.
        with _database_url_environment(db_url):
            command.upgrade(cfg, "head")

    # Shadow checks (fast invariants)
    try:
        import subprocess

        cmd = [sys.executable, "scripts/shadow_migration_check.py", "--db-url", db_url]
        print(f"[verify] running: {' '.join(cmd)}")
        return subprocess.call(cmd)
    except Exception as exc:
        print(f"[verify] failed to run shadow_migration_check: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
